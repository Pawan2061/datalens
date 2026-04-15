from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, Header, Depends

from app.config import settings
from app.db.insight_db import insight_db
import httpx

from app.schemas.persistence import (
    GitHubLoginRequest,
    GoogleLoginRequest,
    LoginRequest,
    LoginResponse,
    UserDoc,
)

router = APIRouter()

# ── JWT helpers ──────────────────────────────────────────────────────

JWT_SECRET = settings.jwt_secret or "datalens-dev-secret-change-me"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72
ADMIN_EMAIL = settings.admin_email


def _create_jwt(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── Legacy base64 token helpers (backward compat) ───────────────────

def _make_token(user_id: str, email: str) -> str:
    raw = f"{user_id}:{email}"
    return base64.b64encode(raw.encode()).decode()


def _decode_legacy_token(token: str) -> tuple[str, str]:
    raw = base64.b64decode(token.encode()).decode()
    parts = raw.split(":", 1)
    return parts[0], parts[1]


# ── Determine if a user should be auto-admin ────────────────────────

def _should_be_admin(email: str) -> bool:
    """Return True if this email should get admin role."""
    if ADMIN_EMAIL and email.strip().lower() == ADMIN_EMAIL.strip().lower():
        return True
    return False


async def _is_first_user() -> bool:
    """Check if there are zero users in the database."""
    if not insight_db.is_ready:
        return False
    users = insight_db.container("users")
    results = list(
        users.query_items(query="SELECT * FROM c", enable_cross_partition_query=True)
    )
    return len(results) == 0


# ── Dependencies ─────────────────────────────────────────────────────

async def get_current_user(authorization: str = Header(None)) -> dict:
    """Dependency: extract user from Bearer token (JWT or legacy base64).

    Returns the full user dict from Cosmos DB, with daily counters reset
    if the date has changed.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = authorization[7:]

    user_id: str | None = None
    email: str | None = None

    # Try JWT first
    jwt_error = ""
    try:
        payload = _decode_jwt(token)
        user_id = payload["sub"]
        email = payload.get("email", "")
    except jwt.ExpiredSignatureError:
        jwt_error = "Token expired"
    except jwt.InvalidTokenError as e:
        jwt_error = f"Invalid JWT: {e}"

    # Fall back to legacy base64 token
    if user_id is None:
        try:
            user_id, email = _decode_legacy_token(token)
        except Exception:
            detail = jwt_error or "Invalid token"
            raise HTTPException(status_code=401, detail=detail)

    if not insight_db.is_ready:
        # Fallback: return minimal dict when DB is down
        return {"id": user_id, "email": email or "", "role": "user", "status": "active"}

    users = insight_db.container("users")
    query = "SELECT * FROM c WHERE c.id = @id"
    params = [{"name": "@id", "value": user_id}]
    results = list(
        users.query_items(
            query=query, parameters=params, enable_cross_partition_query=True
        )
    )

    if not results:
        raise HTTPException(status_code=404, detail="User not found")

    doc = results[0]

    # Check if user is active (admins always pass)
    status = doc.get("status", "pending")
    role = doc.get("role", "user")
    if status != "active" and role != "admin":
        raise HTTPException(
            status_code=403,
            detail=f"Account is {status}. Contact admin for access.",
        )

    # Check expiry
    expiry = doc.get("expiry_date", "")
    if expiry:
        try:
            expiry_dt = datetime.fromisoformat(expiry)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            if expiry_dt < datetime.now(timezone.utc):
                raise HTTPException(
                    status_code=403,
                    detail="Your access has expired. Contact admin.",
                )
        except (ValueError, TypeError):
            pass

    # Reset daily counters if date changed
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")
    changed = False

    if doc.get("usage_reset_date", "") != today_str:
        doc["today_questions"] = 0
        doc["today_tokens"] = 0
        doc["today_cost_usd"] = 0.0
        doc["usage_reset_date"] = today_str
        changed = True

    if doc.get("month_reset_date", "") != month_str:
        doc["month_cost_usd"] = 0.0
        doc["month_reset_date"] = month_str
        changed = True

    if changed:
        users.upsert_item(doc)

    # Return clean dict (strip Cosmos metadata)
    return {k: v for k, v in doc.items() if not k.startswith("_")}


async def get_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Dependency: require admin role."""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


async def get_manager_or_admin(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Dependency: require manager or admin role."""
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Manager or admin access required")
    return current_user


# ── Routes ───────────────────────────────────────────────────────────

@router.post("/api/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    users = insight_db.container("users")
    email_lower = req.email.strip().lower()

    # Try to find existing user by email (partition key query)
    query = "SELECT * FROM c WHERE c.email = @email"
    params = [{"name": "@email", "value": email_lower}]
    results = list(
        users.query_items(
            query=query, parameters=params, partition_key=email_lower
        )
    )

    now = datetime.now(timezone.utc).isoformat()

    if results:
        user_doc = results[0]
        user_doc["last_login_at"] = now
        user_doc["name"] = req.name.strip()
        users.upsert_item(user_doc)
        user = UserDoc(**{k: v for k, v in user_doc.items() if not k.startswith("_")})
    else:
        # Determine role/status for new user
        first_user = await _is_first_user()
        is_admin = first_user or _should_be_admin(email_lower)
        user = UserDoc(
            email=email_lower,
            name=req.name.strip(),
            role="admin" if is_admin else "user",
            status="active" if is_admin else "pending",
        )
        users.create_item(user.model_dump())

    token = _create_jwt(user.id, user.email, user.role)
    return LoginResponse(user=user, token=token)


@router.post("/api/auth/google", response_model=LoginResponse)
async def google_login(req: GoogleLoginRequest):
    """Google SSO login. Verifies the Google ID token and creates/finds user."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    google_client_id = settings.google_client_id
    if not google_client_id:
        raise HTTPException(
            status_code=501,
            detail="Google SSO not configured (GOOGLE_CLIENT_ID not set)",
        )

    # Verify the Google ID token
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests

        idinfo = id_token.verify_oauth2_token(
            req.credential,
            google_requests.Request(),
            google_client_id,
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid Google token: {e}")

    email = idinfo.get("email", "").strip().lower()
    name = idinfo.get("name", email.split("@")[0])
    picture = idinfo.get("picture", "")

    if not email:
        raise HTTPException(status_code=400, detail="No email in Google token")

    users = insight_db.container("users")
    now = datetime.now(timezone.utc).isoformat()

    # Find existing user
    query = "SELECT * FROM c WHERE c.email = @email"
    params = [{"name": "@email", "value": email}]
    results = list(
        users.query_items(query=query, parameters=params, partition_key=email)
    )

    if results:
        user_doc = results[0]
        user_doc["last_login_at"] = now
        user_doc["name"] = name
        if picture:
            user_doc["avatar_url"] = picture
        users.upsert_item(user_doc)
        user = UserDoc(**{k: v for k, v in user_doc.items() if not k.startswith("_")})
    else:
        first_user = await _is_first_user()
        is_admin = first_user or _should_be_admin(email)
        user = UserDoc(
            email=email,
            name=name,
            avatar_url=picture,
            role="admin" if is_admin else "user",
            status="active" if is_admin else "pending",
        )
        users.create_item(user.model_dump())

    token = _create_jwt(user.id, user.email, user.role)
    return LoginResponse(user=user, token=token)


@router.post("/api/auth/github", response_model=LoginResponse)
async def github_login(req: GitHubLoginRequest):
    """GitHub SSO login. Exchanges code for access token, fetches profile."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    gh_client_id = settings.github_client_id
    gh_client_secret = settings.github_client_secret
    if not gh_client_id or not gh_client_secret:
        raise HTTPException(
            status_code=501,
            detail="GitHub SSO not configured (GITHUB_CLIENT_ID / SECRET not set)",
        )

    # Exchange code for access token
    try:
        async with httpx.AsyncClient() as client:
            token_resp = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": gh_client_id,
                    "client_secret": gh_client_secret,
                    "code": req.code,
                },
                headers={"Accept": "application/json"},
                timeout=15,
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise HTTPException(
                    status_code=401,
                    detail=f"GitHub token exchange failed: {token_data.get('error_description', 'unknown')}",
                )

            # Fetch user profile
            user_resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=10,
            )
            gh_user = user_resp.json()

            # Fetch primary email (may be private)
            email = gh_user.get("email") or ""
            if not email:
                emails_resp = await client.get(
                    "https://api.github.com/user/emails",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                    timeout=10,
                )
                for e in emails_resp.json():
                    if e.get("primary"):
                        email = e["email"]
                        break
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"GitHub auth failed: {e}")

    name = gh_user.get("name") or gh_user.get("login", "")
    avatar = gh_user.get("avatar_url", "")
    email = email.strip().lower()

    if not email:
        raise HTTPException(status_code=400, detail="Could not get email from GitHub")

    users = insight_db.container("users")
    now = datetime.now(timezone.utc).isoformat()

    query = "SELECT * FROM c WHERE c.email = @email"
    params = [{"name": "@email", "value": email}]
    results = list(
        users.query_items(query=query, parameters=params, partition_key=email)
    )

    if results:
        user_doc = results[0]
        user_doc["last_login_at"] = now
        user_doc["name"] = name
        if avatar:
            user_doc["avatar_url"] = avatar
        users.upsert_item(user_doc)
        user = UserDoc(**{k: v for k, v in user_doc.items() if not k.startswith("_")})
    else:
        first_user = await _is_first_user()
        is_admin = first_user or _should_be_admin(email)
        user = UserDoc(
            email=email,
            name=name,
            avatar_url=avatar,
            role="admin" if is_admin else "user",
            status="active" if is_admin else "pending",
        )
        users.create_item(user.model_dump())

    token = _create_jwt(user.id, user.email, user.role)
    return LoginResponse(user=user, token=token)


@router.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user
