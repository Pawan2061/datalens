from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.routes.users import get_admin_user
from app.db.insight_db import insight_db
from app.schemas.persistence import AdminUserUpdate

router = APIRouter()


def _clean(doc: dict) -> dict:
    """Strip Cosmos DB metadata keys from a document."""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


# ── List all users ───────────────────────────────────────────────────

@router.get("/api/admin/users")
async def list_users(admin: dict = Depends(get_admin_user)):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    users = insight_db.container("users")
    query = "SELECT * FROM c ORDER BY c.created_at DESC"
    results = list(
        users.query_items(query=query, enable_cross_partition_query=True)
    )
    return [_clean(doc) for doc in results]


# ── Get single user ─────────────────────────────────────────────────

@router.get("/api/admin/users/{user_id}")
async def get_user(user_id: str, admin: dict = Depends(get_admin_user)):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

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
    return _clean(results[0])


# ── Update user (approve, set limits, suspend, change role) ─────────

@router.put("/api/admin/users/{user_id}")
async def update_user(
    user_id: str,
    body: AdminUserUpdate,
    admin: dict = Depends(get_admin_user),
):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

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

    # Apply updates from the request body
    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        doc[key] = value

    users.upsert_item(doc)
    return _clean(doc)


# ── Delete user ──────────────────────────────────────────────────────

@router.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    # Prevent self-deletion
    if user_id == admin.get("id"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

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
    users.delete_item(item=doc["id"], partition_key=doc["email"])
    return {"status": "deleted", "user_id": user_id}


# ── Dashboard stats ──────────────────────────────────────────────────

@router.get("/api/admin/stats")
async def admin_stats(admin: dict = Depends(get_admin_user)):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    users_container = insight_db.container("users")
    all_users = list(
        users_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        )
    )

    total_users = len(all_users)
    active_users = sum(1 for u in all_users if u.get("status") == "active")
    pending_users = sum(1 for u in all_users if u.get("status") == "pending")
    suspended_users = sum(1 for u in all_users if u.get("status") == "suspended")

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    total_questions_today = 0
    total_tokens_today = 0
    total_cost_today = 0.0
    total_cost_month = 0.0

    for u in all_users:
        if u.get("usage_reset_date", "") == today_str:
            total_questions_today += u.get("today_questions", 0)
            total_tokens_today += u.get("today_tokens", 0)
            total_cost_today += u.get("today_cost_usd", 0.0)
        if u.get("month_reset_date", "") == month_str:
            total_cost_month += u.get("month_cost_usd", 0.0)

    # Recent signups (last 5)
    sorted_users = sorted(
        all_users, key=lambda u: u.get("created_at", ""), reverse=True
    )
    recent_signups = [_clean(u) for u in sorted_users[:5]]

    return {
        "total_users": total_users,
        "active_users": active_users,
        "pending_users": pending_users,
        "suspended_users": suspended_users,
        "total_questions_today": total_questions_today,
        "total_tokens_today": total_tokens_today,
        "total_cost_today": round(total_cost_today, 4),
        "total_cost_month": round(total_cost_month, 4),
        "recent_signups": recent_signups,
    }


# ── Usage logs ───────────────────────────────────────────────────────

@router.get("/api/admin/usage")
async def admin_usage(
    limit: int = 50,
    admin: dict = Depends(get_admin_user),
):
    """Return recent usage log entries across all users."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    try:
        usage_logs = insight_db.container("usage_logs")
        results = list(
            usage_logs.query_items(
                query="SELECT * FROM c ORDER BY c.timestamp DESC",
                enable_cross_partition_query=True,
            )
        )
        return [_clean(doc) for doc in results[:limit]]
    except Exception:
        return []


# ── Workspaces (enriched with owner + member details) ────────────────

@router.get("/api/admin/workspaces")
async def admin_workspaces(admin: dict = Depends(get_admin_user)):
    """Return all workspaces enriched with owner info, member details, and metrics."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    ws_container = insight_db.container("workspaces")
    all_ws = list(ws_container.query_items(
        query="SELECT * FROM c ORDER BY c.last_active_at DESC",
        enable_cross_partition_query=True,
    ))

    # Fetch all users for lookup
    users_container = insight_db.container("users")
    all_users = list(users_container.query_items(
        query="SELECT c.id, c.email, c.name, c.avatar_url, c.role, c.status FROM c",
        enable_cross_partition_query=True,
    ))
    user_by_id = {u["id"]: u for u in all_users}
    user_by_email = {u["email"]: u for u in all_users}

    # Fetch analytics events for metrics
    analytics_events: list[dict] = []
    try:
        ae_container = insight_db.container("analytics_events")
        analytics_events = list(ae_container.query_items(
            query="SELECT c.workspace_id, c.tokens_used, c.cost_usd FROM c",
            enable_cross_partition_query=True,
        ))
    except Exception:
        pass

    # Aggregate metrics per workspace
    ws_metrics: dict[str, dict] = {}
    for e in analytics_events:
        wid = e.get("workspace_id", "")
        if wid not in ws_metrics:
            ws_metrics[wid] = {"queries": 0, "tokens": 0, "cost": 0.0}
        ws_metrics[wid]["queries"] += 1
        ws_metrics[wid]["tokens"] += e.get("tokens_used", 0)
        ws_metrics[wid]["cost"] += e.get("cost_usd", 0.0)

    # Enrich workspaces
    result = []
    for ws in all_ws:
        owner_id = ws.get("owner_id", "")
        owner = user_by_id.get(owner_id, {})

        # Resolve members
        members_raw = ws.get("members", [])
        members_enriched = []
        for m in members_raw:
            email = m.get("email", "") if isinstance(m, dict) else m
            user_info = user_by_email.get(email, {})
            members_enriched.append({
                "email": email,
                "name": user_info.get("name", email.split("@")[0]),
                "avatar_url": user_info.get("avatar_url", ""),
                "status": user_info.get("status", "unknown"),
                "added_at": m.get("added_at", "") if isinstance(m, dict) else "",
            })

        metrics = ws_metrics.get(ws.get("id", ""), {"queries": 0, "tokens": 0, "cost": 0.0})

        result.append({
            "id": ws.get("id"),
            "name": ws.get("name", ""),
            "description": ws.get("description", ""),
            "icon": ws.get("icon", ""),
            "created_at": ws.get("created_at", ""),
            "last_active_at": ws.get("last_active_at", ""),
            "connection_count": len(ws.get("connection_ids", []) or ws.get("connections", [])),
            "api_tools_count": len(ws.get("api_tools", [])),
            "owner": {
                "id": owner_id,
                "name": owner.get("name", "Unknown"),
                "email": owner.get("email", ""),
                "avatar_url": owner.get("avatar_url", ""),
                "role": owner.get("role", "user"),
            },
            "members": members_enriched,
            "member_count": len(members_enriched),
            "metrics": {
                "total_queries": metrics["queries"],
                "total_tokens": metrics["tokens"],
                "total_cost": round(metrics["cost"], 4),
            },
        })

    return result


# ── Delete workspace (admin) ────────────────────────────────────────

@router.delete("/api/admin/workspaces/{workspace_id}")
async def admin_delete_workspace(
    workspace_id: str,
    admin: dict = Depends(get_admin_user),
):
    """Admin can delete any workspace and cascade-delete sessions + canvas."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    ws_container = insight_db.container("workspaces")

    # Find workspace (cross-partition since admin may not know owner_id)
    results = list(ws_container.query_items(
        query="SELECT * FROM c WHERE c.id = @id",
        parameters=[{"name": "@id", "value": workspace_id}],
        enable_cross_partition_query=True,
    ))
    if not results:
        raise HTTPException(status_code=404, detail="Workspace not found")

    ws_doc = results[0]
    owner_id = ws_doc.get("owner_id", "")

    # Delete workspace
    ws_container.delete_item(item=workspace_id, partition_key=owner_id)

    # Cascade: delete sessions
    try:
        sess_container = insight_db.container("sessions")
        sessions = list(sess_container.query_items(
            query="SELECT c.id FROM c WHERE c.workspace_id = @wid",
            parameters=[{"name": "@wid", "value": workspace_id}],
            partition_key=workspace_id,
        ))
        for s in sessions:
            sess_container.delete_item(item=s["id"], partition_key=workspace_id)
    except Exception:
        pass

    # Cascade: delete canvas state
    try:
        canvas_container = insight_db.container("canvas_states")
        canvas_container.delete_item(item=workspace_id, partition_key=workspace_id)
    except Exception:
        pass

    # Cascade: delete analytics events
    try:
        ae_container = insight_db.container("analytics_events")
        events = list(ae_container.query_items(
            query="SELECT c.id FROM c WHERE c.workspace_id = @wid",
            parameters=[{"name": "@wid", "value": workspace_id}],
            partition_key=workspace_id,
        ))
        for e in events:
            ae_container.delete_item(item=e["id"], partition_key=workspace_id)
    except Exception:
        pass

    return {"status": "deleted", "workspace_id": workspace_id}
