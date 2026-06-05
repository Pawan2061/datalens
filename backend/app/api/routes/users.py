from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, HTTPException, Header, Depends

from app.config import settings
from app.db.insight_db import insight_db
import httpx

from app.auth.password import verify_password
from app.schemas.persistence import (
    LoginRequest,
    LoginResponse,
    UserDoc,
)

router = APIRouter()

# ── JWT helpers ──────────────────────────────────────────────────────

JWT_SECRET = settings.jwt_secret or "datalens-dev-secret-change-me"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 72


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

def _decode_legacy_token(token: str) -> tuple[str, str]:
    raw = base64.b64decode(token.encode()).decode()
    parts = raw.split(":", 1)
    return parts[0], parts[1]


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

    # Return clean dict (strip Cosmos metadata and sensitive fields)
    return {k: v for k, v in doc.items() if not k.startswith("_") and k != "password_hash"}


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
    """Dependency: require manager, admin, or moderator role.

    Moderator is a read-only dashboard/analytics viewer (see
    ``get_admin_or_moderator``); it is included here so moderators can load the
    analytics dashboard alongside managers and admins.
    """
    if current_user.get("role") not in ("admin", "manager", "moderator"):
        raise HTTPException(status_code=403, detail="Manager or admin access required")
    return current_user


async def get_admin_or_moderator(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Dependency: require admin or moderator role.

    Moderators are read-only: they may VIEW admin dashboard data (stats, users,
    workspaces) but every mutating endpoint (create/update/delete user, delete
    workspace) and the usage-logs endpoint stays gated by ``get_admin_user``.
    Managers are intentionally excluded so their existing access is unchanged.
    """
    if current_user.get("role") not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


# ── reCAPTCHA ────────────────────────────────────────────────────────

async def _verify_recaptcha(token: str) -> bool | None:
    """Verify reCAPTCHA Enterprise token via Assessment API.

    Returns True (valid, score >= 0.5), False (invalid/bot), None (network error).
    Returns True immediately when Enterprise credentials are not configured (dev mode).
    """
    project_id = settings.recaptcha_project_id
    api_key = settings.recaptcha_gcp_api_key
    site_key = settings.recaptcha_enterprise_site_key
    if not project_id or not api_key:
        return True
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://recaptchaenterprise.googleapis.com/v1/projects/{project_id}/assessments?key={api_key}",
                json={"event": {"token": token, "siteKey": site_key, "expectedAction": "LOGIN"}},
                timeout=10,
            )
            data = resp.json()
            if not data.get("tokenProperties", {}).get("valid", False):
                return False
            score = data.get("riskAnalysis", {}).get("score", 0.0)
            return score >= 0.5
    except Exception:
        return None


# ── Routes ───────────────────────────────────────────────────────────

@router.post("/api/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    captcha = await _verify_recaptcha(req.recaptcha_token)
    if captcha is None:
        raise HTTPException(status_code=503, detail="CAPTCHA service unavailable. Please try again.")
    if not captcha:
        raise HTTPException(status_code=400, detail="CAPTCHA verification failed. Please try again.")

    users = insight_db.container("users")
    email_lower = req.email.strip().lower()

    query = "SELECT * FROM c WHERE c.email = @email"
    params = [{"name": "@email", "value": email_lower}]
    results = list(
        users.query_items(query=query, parameters=params, partition_key=email_lower)
    )

    _invalid = HTTPException(status_code=401, detail="Invalid email or password.")

    if not results:
        raise _invalid

    user_doc = results[0]
    if not verify_password(req.password, user_doc.get("password_hash", "")):
        raise _invalid

    user_doc["last_login_at"] = datetime.now(timezone.utc).isoformat()
    users.upsert_item(user_doc)
    user = UserDoc(**{k: v for k, v in user_doc.items() if not k.startswith("_") and k != "password_hash"})

    token = _create_jwt(user.id, user.email, user.role)
    return LoginResponse(user=user, token=token)


@router.get("/api/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    # Surface the cost thresholds so the frontend warning banner / admin UI use
    # server values rather than hard-coded numbers that could drift from config.
    return {
        **current_user,
        "cost_warn_threshold_usd": settings.cost_alert_threshold_usd,
        "cost_block_threshold_usd_per_day": settings.cost_block_threshold_usd_per_day,
    }
