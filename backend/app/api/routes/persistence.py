from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from app.agent.api_tool_cache import invalidate_workspace_api_tools_cache
from app.db.insight_db import insight_db
from app.api.routes.users import get_current_user
from app.schemas.persistence import (
    WorkspaceDoc, WorkspaceCreateRequest, WorkspaceUpdateRequest,
    SessionDoc, SessionUpsertRequest, SessionSummary,
    CanvasStateDoc, CanvasSaveRequest,
    AddMemberRequest, WorkspaceMember, ApiToolConfig,
)

router = APIRouter()


def _require_db():
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")


def _uid(current_user: dict) -> str:
    """Extract user_id string from the current_user dict."""
    return current_user.get("id", "")


def _clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _verify_workspace_access(workspace_doc: dict, current_user: dict, require_owner: bool = False):
    """Check if user can access this workspace.

    - Admin: universal access
    - Owner: always has access
    - Member: read/use access (unless require_owner=True)
    """
    role = current_user.get("role", "user")
    user_id = current_user.get("id", "")
    email = current_user.get("email", "")

    if role == "admin":
        return  # Admin has universal access

    if workspace_doc.get("owner_id") == user_id:
        return  # Owner always has access

    if require_owner:
        raise HTTPException(status_code=403, detail="Only the workspace owner can do this")

    # Check members list
    members = workspace_doc.get("members", [])
    member_emails = [m.get("email", "") if isinstance(m, dict) else m for m in members]
    if email in member_emails:
        return  # Member has access

    raise HTTPException(status_code=403, detail="Access denied to this workspace")


def _fetch_workspace(workspace_id: str) -> dict:
    """Fetch a workspace by ID (cross-partition)."""
    container = insight_db.container("workspaces")
    query = "SELECT * FROM c WHERE c.id = @wid"
    params = [{"name": "@wid", "value": workspace_id}]
    results = list(container.query_items(
        query=query, parameters=params, enable_cross_partition_query=True
    ))
    if not results:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return results[0]


# -- Workspaces ----------------------------------------------------------

@router.get("/api/workspaces")
async def list_workspaces(current_user: dict = Depends(get_current_user)):
    _require_db()
    role = current_user.get("role", "user")
    user_id = _uid(current_user)
    email = current_user.get("email", "")
    container = insight_db.container("workspaces")

    if role == "admin":
        # Admin sees everything
        query = "SELECT * FROM c ORDER BY c.last_active_at DESC"
        results = list(container.query_items(query=query, enable_cross_partition_query=True))
    elif role == "manager":
        # Manager sees workspaces they own + workspaces they're a member of
        # First: owned workspaces
        owned_query = "SELECT * FROM c WHERE c.owner_id = @owner_id"
        owned_params = [{"name": "@owner_id", "value": user_id}]
        owned = list(container.query_items(query=owned_query, parameters=owned_params, partition_key=user_id))

        # Also: workspaces where they are a member (from other managers/admins)
        member_query = "SELECT * FROM c WHERE ARRAY_CONTAINS(c.members, @email_obj, true)"
        member_params = [{"name": "@email_obj", "value": email}]
        try:
            member_results = list(container.query_items(
                query="SELECT * FROM c",
                enable_cross_partition_query=True,
            ))
            # Filter in Python — Cosmos doesn't support ARRAY_CONTAINS on nested objects well
            member_ws = [
                ws for ws in member_results
                if ws.get("owner_id") != user_id
                and email in [m.get("email", "") if isinstance(m, dict) else m for m in ws.get("members", [])]
            ]
        except Exception:
            member_ws = []

        results = owned + member_ws
        # Sort by last_active_at desc
        results.sort(key=lambda w: w.get("last_active_at", ""), reverse=True)
    else:
        # Regular user: only workspaces where their email is in members
        all_ws = list(container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        ))
        results = [
            ws for ws in all_ws
            if email in [m.get("email", "") if isinstance(m, dict) else m for m in ws.get("members", [])]
        ]
        results.sort(key=lambda w: w.get("last_active_at", ""), reverse=True)

    return [_clean(doc) for doc in results]


@router.post("/api/workspaces")
async def create_workspace(data: WorkspaceCreateRequest, current_user: dict = Depends(get_current_user)):
    _require_db()
    role = current_user.get("role", "user")
    if role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Only managers and admins can create workspaces")

    user_id = _uid(current_user)
    container = insight_db.container("workspaces")
    doc = WorkspaceDoc(
        owner_id=user_id,
        name=data.name,
        description=data.description,
        icon=data.icon,
        connections=data.connections,
        connection_ids=data.connection_ids,
    )
    container.create_item(doc.model_dump())
    return doc.model_dump()


@router.put("/api/workspaces/{workspace_id}")
async def update_workspace(workspace_id: str, data: WorkspaceUpdateRequest, current_user: dict = Depends(get_current_user)):
    _require_db()
    existing = _fetch_workspace(workspace_id)
    _verify_workspace_access(existing, current_user, require_owner=True)

    updates = data.model_dump(exclude_none=True)
    for key, value in updates.items():
        existing[key] = value
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    container = insight_db.container("workspaces")
    container.upsert_item(existing)
    return _clean(existing)


@router.delete("/api/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    existing = _fetch_workspace(workspace_id)
    _verify_workspace_access(existing, current_user, require_owner=True)

    ws_container = insight_db.container("workspaces")
    ws_container.delete_item(item=workspace_id, partition_key=existing["owner_id"])

    # Cascade: delete all sessions
    sess_container = insight_db.container("sessions")
    sessions = list(sess_container.query_items(
        query="SELECT c.id FROM c WHERE c.workspace_id = @wid",
        parameters=[{"name": "@wid", "value": workspace_id}],
        partition_key=workspace_id,
    ))
    for s in sessions:
        sess_container.delete_item(item=s["id"], partition_key=workspace_id)

    # Cascade: delete canvas state
    canvas_container = insight_db.container("canvas_states")
    try:
        canvas_container.delete_item(item=workspace_id, partition_key=workspace_id)
    except Exception:
        pass


# -- Workspace Members ----------------------------------------------------

@router.get("/api/workspaces/{workspace_id}/members")
async def list_members(workspace_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)
    return ws.get("members", [])


@router.post("/api/workspaces/{workspace_id}/members")
async def add_member(workspace_id: str, body: AddMemberRequest, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)

    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    # Check if already a member
    members = ws.get("members", [])
    existing_emails = [m.get("email", "") if isinstance(m, dict) else m for m in members]
    if email in existing_emails:
        raise HTTPException(status_code=409, detail="User is already a member")

    # Add the member
    member = WorkspaceMember(
        email=email,
        added_by=_uid(current_user),
    )
    members.append(member.model_dump())
    ws["members"] = members
    ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    container = insight_db.container("workspaces")
    container.upsert_item(ws)
    return member.model_dump()


@router.delete("/api/workspaces/{workspace_id}/members/{email}")
async def remove_member(workspace_id: str, email: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)

    email_lower = email.strip().lower()
    members = ws.get("members", [])
    new_members = [m for m in members if (m.get("email", "") if isinstance(m, dict) else m) != email_lower]

    if len(new_members) == len(members):
        raise HTTPException(status_code=404, detail="Member not found")

    ws["members"] = new_members
    ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    container = insight_db.container("workspaces")
    container.upsert_item(ws)
    return {"status": "removed", "email": email_lower}


# -- Workspace API Tools --------------------------------------------------

@router.get("/api/workspaces/{workspace_id}/api-tools")
async def list_api_tools(workspace_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user)
    # Mask auth headers for non-owners
    tools = ws.get("api_tools", [])
    if ws.get("owner_id") != _uid(current_user) and current_user.get("role") != "admin":
        masked = []
        for t in tools:
            tc = dict(t)
            tc["headers"] = {k: "***" for k in tc.get("headers", {})}
            masked.append(tc)
        return masked
    return tools


@router.post("/api/workspaces/{workspace_id}/api-tools")
async def add_api_tool(workspace_id: str, body: ApiToolConfig, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)

    body.created_by = _uid(current_user)
    tools = ws.get("api_tools", [])
    tools.append(body.model_dump())
    ws["api_tools"] = tools
    ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    container = insight_db.container("workspaces")
    container.upsert_item(ws)
    invalidate_workspace_api_tools_cache(workspace_id)
    return body.model_dump()


@router.delete("/api/workspaces/{workspace_id}/api-tools/{tool_id}")
async def remove_api_tool(workspace_id: str, tool_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)

    tools = ws.get("api_tools", [])
    new_tools = [t for t in tools if t.get("id") != tool_id]
    if len(new_tools) == len(tools):
        raise HTTPException(status_code=404, detail="Tool not found")

    ws["api_tools"] = new_tools
    ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    container = insight_db.container("workspaces")
    container.upsert_item(ws)
    invalidate_workspace_api_tools_cache(workspace_id)
    return {"status": "deleted", "tool_id": tool_id}


@router.put("/api/workspaces/{workspace_id}/api-tools/{tool_id}")
async def update_api_tool(workspace_id: str, tool_id: str, body: ApiToolConfig, current_user: dict = Depends(get_current_user)):
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)

    tools = ws.get("api_tools", [])
    found = False
    for i, t in enumerate(tools):
        if t.get("id") == tool_id:
            body.id = tool_id  # Preserve original ID
            body.created_at = t.get("created_at", body.created_at)
            body.created_by = t.get("created_by", _uid(current_user))
            tools[i] = body.model_dump()
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Tool not found")

    ws["api_tools"] = tools
    ws["updated_at"] = datetime.now(timezone.utc).isoformat()

    container = insight_db.container("workspaces")
    container.upsert_item(ws)
    invalidate_workspace_api_tools_cache(workspace_id)
    return body.model_dump()


class ApiToolTestRequest(BaseModel):
    test_params: dict = {}  # e.g. {"ITEM_ID": "16314"}


@router.post("/api/workspaces/{workspace_id}/api-tools/{tool_id}/test")
async def test_api_tool(workspace_id: str, tool_id: str, body: ApiToolTestRequest, current_user: dict = Depends(get_current_user)):
    """Test an API tool with sample parameters and return the raw response."""
    _require_db()
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user, require_owner=True)

    tools = ws.get("api_tools", [])
    tool_cfg = next((t for t in tools if t.get("id") == tool_id), None)
    if not tool_cfg:
        raise HTTPException(status_code=404, detail="Tool not found")

    import httpx
    import time

    from app.agent.tools.api_tool_factory import _extract_nested

    endpoint_url = tool_cfg.get("endpoint_url", "")
    req_code = tool_cfg.get("req_code", "")
    method = (tool_cfg.get("method") or "POST").upper()
    auth = tool_cfg.get("auth_config", {}) or {}
    timeout = tool_cfg.get("timeout_seconds", 30)
    auth_mode = (tool_cfg.get("auth_mode") or "static").lower()

    def _mark_status(status: str) -> None:
        for t in tools:
            if t.get("id") == tool_id:
                t["test_status"] = status
        ws["api_tools"] = tools
        insight_db.container("workspaces").upsert_item(ws)
        invalidate_workspace_api_tools_cache(workspace_id)

    # ── Two-step: fetch token, then call data endpoint with it in URL ────
    if auth_mode == "two_step_token":
        token_endpoint = tool_cfg.get("token_endpoint", "")
        if not token_endpoint:
            raise HTTPException(
                status_code=400,
                detail="auth_mode=two_step_token requires token_endpoint",
            )
        token_response_path = tool_cfg.get("token_response_path") or "AUTH_TOKEN"
        token_param_name = tool_cfg.get("token_param_name") or "TOKEN"

        token_fetch_start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                tok_resp = await client.get(token_endpoint)
                tok_resp.raise_for_status()
                tok_data = tok_resp.json()
        except Exception as e:
            _mark_status("failed")
            raise HTTPException(status_code=502, detail=f"Token fetch failed: {str(e)}")

        token_fetch_ms = (time.perf_counter() - token_fetch_start) * 1000
        token_value = _extract_nested(tok_data, token_response_path)
        if not isinstance(token_value, str) or not token_value.strip():
            _mark_status("failed")
            raise HTTPException(
                status_code=502,
                detail=f"Token endpoint did not return a token at '{token_response_path}'",
            )
        token_value = token_value.strip()

        url = endpoint_url
        parts: list[str] = []
        if req_code:
            parts.append(f"reqCode={req_code}")
        if auth.get("apikey"):
            parts.append(f"APIKEY={auth['apikey']}")
        parts.append(f"{token_param_name}={token_value}")
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{'&'.join(parts)}"

        data_start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if method == "POST":
                    resp = await client.post(url, json=body.test_params, headers={"Content-Type": "application/json"})
                else:
                    resp = await client.get(url, params=body.test_params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            _mark_status("failed")
            raise HTTPException(status_code=502, detail=f"API call failed: {str(e)}")

        duration_ms = (time.perf_counter() - data_start) * 1000
        _mark_status("success")
        return {
            "status": "success",
            "auth_mode": "two_step_token",
            "token_fetch_ms": round(token_fetch_ms, 2),
            "duration_ms": round(duration_ms, 2),
            "response": data,
        }

    # ── Static path: unchanged legacy behavior ──────────────────────────
    req_body: dict = {}
    if auth.get("apikey"):
        req_body["APIKEY"] = auth["apikey"]
    if auth.get("token"):
        req_body["TOKEN"] = auth["token"]
    req_body.update(body.test_params)

    url = endpoint_url
    if req_code:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}reqCode={req_code}"

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "POST":
                resp = await client.post(url, json=req_body, headers={"Content-Type": "application/json"})
            else:
                resp = await client.get(url, params=req_body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        _mark_status("failed")
        raise HTTPException(status_code=502, detail=f"API call failed: {str(e)}")

    duration_ms = (time.perf_counter() - start) * 1000
    _mark_status("success")

    return {
        "status": "success",
        "duration_ms": round(duration_ms, 2),
        "response": data,
    }


# -- Sessions -------------------------------------------------------------

async def _verify_session_access(workspace_id: str, current_user: dict):
    """Ensure the user has access to this workspace (for session operations)."""
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user)


@router.get("/api/workspaces/{workspace_id}/sessions")
async def list_sessions(workspace_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    user_id = _uid(current_user)
    await _verify_session_access(workspace_id, current_user)

    container = insight_db.container("sessions")
    query = "SELECT c.id, c.title, c.created_at, c.updated_at FROM c WHERE c.workspace_id = @wid AND c.user_id = @uid ORDER BY c.updated_at DESC"
    params = [
        {"name": "@wid", "value": workspace_id},
        {"name": "@uid", "value": user_id},
    ]
    results = list(container.query_items(query=query, parameters=params, partition_key=workspace_id))
    return [
        SessionSummary(
            id=r["id"],
            title=r.get("title", "New Chat"),
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
        ).model_dump()
        for r in results
    ]


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str, workspace_id: str = Query(...), current_user: dict = Depends(get_current_user)):
    _require_db()
    user_id = _uid(current_user)
    container = insight_db.container("sessions")
    try:
        doc = container.read_item(item=session_id, partition_key=workspace_id)
        if doc.get("user_id") and doc["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied — not your session")
        return _clean(doc)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Session not found")


@router.put("/api/sessions/{session_id}")
async def upsert_session(session_id: str, data: SessionUpsertRequest, current_user: dict = Depends(get_current_user)):
    _require_db()
    user_id = _uid(current_user)
    container = insight_db.container("sessions")
    now = datetime.now(timezone.utc).isoformat()

    try:
        existing = container.read_item(item=session_id, partition_key=data.workspace_id)
        if existing.get("user_id") and existing["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied — not your session")
        existing["title"] = data.title
        existing["messages"] = data.messages
        existing["updated_at"] = now
        container.upsert_item(existing)
        return _clean(existing)
    except HTTPException:
        raise
    except Exception:
        doc = SessionDoc(
            id=session_id,
            workspace_id=data.workspace_id,
            user_id=user_id,
            title=data.title,
            messages=data.messages,
        )
        container.create_item(doc.model_dump())
        return doc.model_dump()


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, workspace_id: str = Query(...), current_user: dict = Depends(get_current_user)):
    _require_db()
    user_id = _uid(current_user)
    container = insight_db.container("sessions")
    try:
        doc = container.read_item(item=session_id, partition_key=workspace_id)
        if doc.get("user_id") and doc["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Access denied — not your session")
        container.delete_item(item=session_id, partition_key=workspace_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@router.delete("/api/workspaces/{workspace_id}/sessions")
async def clear_all_sessions(workspace_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    user_id = _uid(current_user)
    await _verify_session_access(workspace_id, current_user)

    container = insight_db.container("sessions")
    sessions = list(container.query_items(
        query="SELECT c.id FROM c WHERE c.workspace_id = @wid AND c.user_id = @uid",
        parameters=[
            {"name": "@wid", "value": workspace_id},
            {"name": "@uid", "value": user_id},
        ],
        partition_key=workspace_id,
    ))
    deleted = 0
    for s in sessions:
        container.delete_item(item=s["id"], partition_key=workspace_id)
        deleted += 1
    return {"deleted": deleted}


# -- Canvas State ---------------------------------------------------------

@router.get("/api/workspaces/{workspace_id}/canvas")
async def get_canvas_state(workspace_id: str, current_user: dict = Depends(get_current_user)):
    _require_db()
    await _verify_session_access(workspace_id, current_user)

    container = insight_db.container("canvas_states")
    try:
        doc = container.read_item(item=workspace_id, partition_key=workspace_id)
        return _clean(doc)
    except Exception:
        return {"id": workspace_id, "workspace_id": workspace_id, "blocks": [], "updated_at": None}


@router.put("/api/workspaces/{workspace_id}/canvas")
async def save_canvas_state(workspace_id: str, data: CanvasSaveRequest, current_user: dict = Depends(get_current_user)):
    _require_db()
    await _verify_session_access(workspace_id, current_user)

    container = insight_db.container("canvas_states")
    now = datetime.now(timezone.utc).isoformat()
    doc = CanvasStateDoc(
        id=workspace_id,
        workspace_id=workspace_id,
        blocks=data.blocks,
        updated_at=now,
    )
    container.upsert_item(doc.model_dump())
    return doc.model_dump()
