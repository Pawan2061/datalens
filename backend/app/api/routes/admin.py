from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.routes.users import get_admin_user, get_admin_or_moderator
from app.auth.password import hash_password
from app.auth.user_doc_cache import invalidate_cached_user_doc
from app.config import settings
from app.db.insight_db import insight_db
from app.schemas.persistence import AdminUserCreate, AdminUserUpdate
from app.services import user_management

router = APIRouter()


def _is_cost_blocked(doc: dict, today_str: str | None = None) -> bool:
    """Derive whether a user is currently blocked by the daily cost cap.

    Mirrors the rule in auth.quota.check_quota: privileged roles are never
    blocked; a regular user is blocked when today's spend has reached the cap
    and an admin has not re-approved them today. today_cost_usd is only counted
    when it belongs to today's window (usage_reset_date == today) — otherwise
    it is stale from a prior day that hasn't been lazily reset yet.
    """
    if doc.get("role") in ("admin", "manager", "moderator"):
        return False
    cap = settings.cost_block_threshold_usd_per_day
    if cap <= 0:
        return False
    today_str = today_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_cost = (
        doc.get("today_cost_usd", 0.0)
        if doc.get("usage_reset_date", "") == today_str
        else 0.0
    )
    return today_cost >= cap and doc.get("cost_block_cleared_date", "") != today_str


def _clean(doc: dict) -> dict:
    """Strip Cosmos DB metadata and sensitive fields from a document."""
    return {k: v for k, v in doc.items() if not k.startswith("_") and k != "password_hash"}


def _clean_annotated(doc: dict, today_str: str | None = None) -> dict:
    """_clean plus a derived `cost_blocked` flag for admin UI display."""
    out = _clean(doc)
    out["cost_blocked"] = _is_cost_blocked(doc, today_str)
    return out


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _runtime_cache_stats() -> dict:
    from app.agent import cache_warmer
    from app.agent.api_tool_cache import workspace_api_tools_cache_stats
    from app.agent.quick_responses import response_cache
    from app.agent.schema_cache import schema_cache
    from app.agent.tools import api_token_cache
    from app.agent.tools.sql_executor import sql_result_cache_stats
    from app.auth.user_doc_cache import user_doc_cache_stats

    return {
        "response_cache": response_cache.stats(),
        "schema_cache": schema_cache.stats(),
        "workspace_api_tools_cache": workspace_api_tools_cache_stats(),
        "sql_result_cache": sql_result_cache_stats(),
        "api_token_cache": api_token_cache.stats(),
        "user_doc_cache": user_doc_cache_stats(),
        "anthropic_cache_warmer": cache_warmer.stats(),
    }


def _cache_efficiency_summary(
    usage_logs: list[dict],
    analytics_events: list[dict],
    *,
    days: int,
    now: datetime | None = None,
) -> dict:
    """Build a read-only cache/cost summary from persisted usage rows."""
    from app.llm.pricing import resolve_model_pricing

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    recent_usage: list[dict] = []
    for row in usage_logs:
        ts = _parse_timestamp(row.get("timestamp", ""))
        if ts and ts >= cutoff:
            recent_usage.append(row)

    recent_events: list[dict] = []
    for row in analytics_events:
        ts = _parse_timestamp(row.get("timestamp", ""))
        if ts and ts >= cutoff:
            recent_events.append(row)

    prompt_cache_read_tokens = 0
    prompt_cache_creation_tokens = 0
    prompt_cache_read_savings_usd = 0.0
    prompt_cache_creation_overhead_usd = 0.0
    total_usage_cost = 0.0
    total_input_tokens = 0
    total_output_tokens = 0
    model_counts: dict[str, int] = {}

    for row in recent_usage:
        model = row.get("model_name", "") or "unknown"
        model_counts[model] = model_counts.get(model, 0) + 1
        pricing, _matched = resolve_model_pricing(model)
        read_tokens = int(row.get("cache_read_tokens") or 0)
        create_tokens = int(row.get("cache_creation_tokens") or 0)
        prompt_cache_read_tokens += read_tokens
        prompt_cache_creation_tokens += create_tokens
        prompt_cache_read_savings_usd += read_tokens * pricing["input"] * 0.90 / 1_000_000
        prompt_cache_creation_overhead_usd += create_tokens * pricing["input"] * 0.25 / 1_000_000
        total_usage_cost += float(row.get("cost_usd") or 0.0)
        total_input_tokens += int(row.get("input_tokens") or 0)
        total_output_tokens += int(row.get("output_tokens") or 0)

    response_cache_hits = sum(1 for row in recent_events if row.get("cached"))
    total_queries = len(recent_events)
    non_cached_events = max(total_queries - response_cache_hits, 0)
    non_cached_cost = sum(float(row.get("cost_usd") or 0.0) for row in recent_events if not row.get("cached"))
    avg_non_cached_cost = non_cached_cost / non_cached_events if non_cached_events else 0.0
    estimated_response_cache_cost_avoided = response_cache_hits * avg_non_cached_cost

    prompt_cache_requests = sum(
        1
        for row in recent_usage
        if int(row.get("cache_read_tokens") or 0) > 0
        or int(row.get("cache_creation_tokens") or 0) > 0
    )
    prompt_cache_hit_requests = sum(
        1 for row in recent_usage if int(row.get("cache_read_tokens") or 0) > 0
    )

    return {
        "window_days": days,
        "usage_rows": len(recent_usage),
        "analytics_events": total_queries,
        "response_cache": {
            "hits": response_cache_hits,
            "total_queries": total_queries,
            "hit_rate": round(response_cache_hits / total_queries, 4) if total_queries else 0.0,
            "estimated_cost_avoided_usd": round(estimated_response_cache_cost_avoided, 6),
            "avg_non_cached_cost_usd": round(avg_non_cached_cost, 6),
        },
        "anthropic_prompt_cache": {
            "requests_with_cache_tokens": prompt_cache_requests,
            "requests_with_cache_reads": prompt_cache_hit_requests,
            "request_hit_rate": round(prompt_cache_hit_requests / len(recent_usage), 4) if recent_usage else 0.0,
            "cache_read_tokens": prompt_cache_read_tokens,
            "cache_creation_tokens": prompt_cache_creation_tokens,
            "read_savings_usd": round(prompt_cache_read_savings_usd, 6),
            "creation_overhead_usd": round(prompt_cache_creation_overhead_usd, 6),
            "net_estimated_savings_usd": round(
                prompt_cache_read_savings_usd - prompt_cache_creation_overhead_usd,
                6,
            ),
        },
        "llm_usage": {
            "cost_usd": round(total_usage_cost, 6),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model_counts": dict(sorted(model_counts.items())),
        },
    }


# ── Create user (admin-driven) ──────────────────────────────────────

@router.post("/api/admin/users")
async def create_user(body: AdminUserCreate, admin: dict = Depends(get_admin_user)):
    """Pre-create a user bound to a customer_code. Non-admin users created here
    cannot self-signup — they must be created via this endpoint."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    # Regular users must be bound to a customer; admins/managers may be unscoped.
    if body.role == "user" and not body.customer_code.strip():
        raise HTTPException(
            status_code=400,
            detail="customer_code is required when role is 'user'",
        )

    existing = await user_management.find_user_by_email(email)
    if existing:
        raise HTTPException(
            status_code=409,
            detail="A user with this email already exists",
        )

    password_hash = hash_password(body.password) if body.password else ""

    try:
        created = await user_management.create_user_for_customer(
            name=body.name,
            email=email,
            customer_code=body.customer_code,
            role=body.role,
            status=body.status,
            max_questions_per_day=body.max_questions_per_day,
            max_tokens_per_day=body.max_tokens_per_day,
            max_cost_usd_per_month=body.max_cost_usd_per_month,
            expiry_date=body.expiry_date,
            password_hash=password_hash,
        )
    except Exception as exc:
        # Concurrent create_user calls with the same email lose to the
        # UNIQUE(email) constraint. Inspect the constraint name on psycopg's
        # UniqueViolation so we don't also catch unrelated PK collisions.
        try:
            from psycopg.errors import UniqueViolation
        except ImportError:
            UniqueViolation = ()  # type: ignore[assignment]
        if isinstance(exc, UniqueViolation):
            constraint = getattr(getattr(exc, "diag", None), "constraint_name", "") or ""
            if "email" in constraint.lower():
                raise HTTPException(
                    status_code=409,
                    detail="A user with this email already exists",
                )
        raise
    return created


# ── List users by customer ──────────────────────────────────────────

@router.get("/api/admin/users/by-customer/{customer_code}")
async def list_users_for_customer(
    customer_code: str,
    admin: dict = Depends(get_admin_or_moderator),
):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")
    return await user_management.list_users_by_customer(customer_code)


# ── List all users ───────────────────────────────────────────────────

@router.get("/api/admin/users")
async def list_users(admin: dict = Depends(get_admin_or_moderator)):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    users = insight_db.container("users")
    query = "SELECT * FROM c ORDER BY c.created_at DESC"
    results = list(
        users.query_items(query=query, enable_cross_partition_query=True)
    )
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return [_clean_annotated(doc, today_str) for doc in results]


# ── Get single user ─────────────────────────────────────────────────

@router.get("/api/admin/users/{user_id}")
async def get_user(user_id: str, admin: dict = Depends(get_admin_or_moderator)):
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
    return _clean_annotated(results[0])


# ── Approve spend (clear a daily cost block) ────────────────────────

@router.post("/api/admin/users/{user_id}/approve-spend")
async def approve_spend(user_id: str, admin: dict = Depends(get_admin_user)):
    """Re-enable a customer blocked by the daily cost cap, for the rest of today.

    Stamps cost_block_cleared_date = today (UTC). While that equals today the
    daily $ block is suppressed in check_quota; the cap re-arms automatically
    the next day. Today's spend is preserved (still counts toward monthly/total).
    """
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
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    doc["cost_block_cleared_date"] = today_str
    users.upsert_item(doc)
    invalidate_cached_user_doc(user_id)  # hygiene; gating already reads fresh
    return _clean_annotated(doc, today_str)


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
    if "password" in update_data:
        doc["password_hash"] = hash_password(update_data.pop("password"))
    for key, value in update_data.items():
        doc[key] = value

    users.upsert_item(doc)
    return _clean_annotated(doc)


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
async def admin_stats(admin: dict = Depends(get_admin_or_moderator)):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    users_container = insight_db.container("users")
    all_users = list(
        users_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        )
    )

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    total_users = len(all_users)
    active_users = sum(1 for u in all_users if u.get("status") == "active")
    pending_users = sum(1 for u in all_users if u.get("status") == "pending")
    suspended_users = sum(1 for u in all_users if u.get("status") == "suspended")
    cost_blocked_users = sum(1 for u in all_users if _is_cost_blocked(u, today_str))

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
    recent_signups = [_clean_annotated(u, today_str) for u in sorted_users[:5]]

    return {
        "total_users": total_users,
        "active_users": active_users,
        "pending_users": pending_users,
        "suspended_users": suspended_users,
        "cost_blocked_users": cost_blocked_users,
        "total_questions_today": total_questions_today,
        "total_tokens_today": total_tokens_today,
        "total_cost_today": round(total_cost_today, 4),
        "total_cost_month": round(total_cost_month, 4),
        "recent_signups": recent_signups,
    }


# ── Cache efficiency ─────────────────────────────────────────────────

@router.get("/api/admin/cache-efficiency")
async def admin_cache_efficiency(
    days: int = 7,
    admin: dict = Depends(get_admin_user),
):
    """Return persisted and in-memory cache efficiency metrics."""
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    days = max(1, min(int(days or 7), 90))

    try:
        usage_logs = list(
            insight_db.container("usage_logs").query_items(
                query="SELECT * FROM c ORDER BY c.timestamp DESC",
                enable_cross_partition_query=True,
            )
        )
    except Exception:
        usage_logs = []

    try:
        analytics_events = list(
            insight_db.container("analytics_events").query_items(
                query="SELECT * FROM c ORDER BY c.timestamp DESC",
                enable_cross_partition_query=True,
            )
        )
    except Exception:
        analytics_events = []

    return {
        "summary": _cache_efficiency_summary(
            [_clean(row) for row in usage_logs],
            [_clean(row) for row in analytics_events],
            days=days,
        ),
        "runtime_caches": _runtime_cache_stats(),
    }


# ── Usage logs ───────────────────────────────────────────────────────

@router.get("/api/admin/usage")
async def admin_usage(
    limit: int = 50,
    admin: dict = Depends(get_admin_user),
):
    """Return recent usage log entries across all users.

    Enriches each row with user_name / user_email so the admin Usage Logs
    table can render the user column (UsageRecord itself only carries
    user_id). Pulls cache token fields through untouched — the writer in
    auth/quota.record_usage persists them.
    """
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
        trimmed = [_clean(doc) for doc in results[:limit]]

        # Batch-resolve user_id → (name, email). One query for the distinct
        # set of user_ids in this page, rather than one query per row.
        user_ids = {row.get("user_id", "") for row in trimmed if row.get("user_id")}
        user_map: dict[str, dict] = {}
        if user_ids:
            try:
                users_container = insight_db.container("users")
                # Cosmos doesn't support parameterized IN with arrays in every
                # SDK version — build the query with quoted literals (ids are
                # 12-char hex, safe to inline; still defense-check).
                safe_ids = [uid for uid in user_ids if uid.replace("-", "").isalnum()]
                if safe_ids:
                    id_list = ", ".join(f"'{uid}'" for uid in safe_ids)
                    users_q = (
                        f"SELECT c.id, c.name, c.email FROM c "
                        f"WHERE c.id IN ({id_list})"
                    )
                    for u in users_container.query_items(
                        query=users_q, enable_cross_partition_query=True,
                    ):
                        user_map[u.get("id", "")] = {
                            "name": u.get("name", ""),
                            "email": u.get("email", ""),
                        }
            except Exception:
                pass  # Enrichment is best-effort — fall back to raw user_id

        for row in trimmed:
            uid = row.get("user_id", "")
            u = user_map.get(uid, {})
            row["user_name"] = u.get("name", "") or uid or "Unknown"
            row["user_email"] = u.get("email", "")

        return trimmed
    except Exception:
        return []


# ── Workspaces (enriched with owner + member details) ────────────────

@router.get("/api/admin/workspaces")
async def admin_workspaces(admin: dict = Depends(get_admin_or_moderator)):
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
            "scope_customers": ws.get("scope_customers", []),
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
