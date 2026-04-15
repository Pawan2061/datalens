"""Analytics dashboard API — available to admin and manager roles."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.users import get_current_user, get_manager_or_admin
from app.db.insight_db import insight_db

router = APIRouter()


def _clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _get_manager_workspace_ids(user_id: str) -> list[str]:
    """Get workspace IDs owned by a manager."""
    container = insight_db.container("workspaces")
    query = "SELECT c.id FROM c WHERE c.owner_id = @uid"
    params = [{"name": "@uid", "value": user_id}]
    results = list(container.query_items(query=query, parameters=params, partition_key=user_id))
    return [r["id"] for r in results]


@router.get("/api/analytics/dashboard")
async def analytics_dashboard(
    period: str = Query("30d", regex="^(7d|30d|90d)$"),
    workspace_id: str = Query("", description="Filter by workspace"),
    current_user: dict = Depends(get_manager_or_admin),
):
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")

    days = {"7d": 7, "30d": 30, "90d": 90}[period]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    role = current_user.get("role", "user")

    # Determine which workspaces to include
    if workspace_id:
        ws_filter = [workspace_id]
    elif role == "admin":
        ws_filter = None  # None = all
    else:
        ws_filter = _get_manager_workspace_ids(current_user.get("id", ""))

    # Fetch analytics events
    try:
        container = insight_db.container("analytics_events")
        if ws_filter is None:
            query = "SELECT * FROM c WHERE c.timestamp >= @cutoff ORDER BY c.timestamp DESC"
            params = [{"name": "@cutoff", "value": cutoff}]
            events = list(container.query_items(query=query, parameters=params, enable_cross_partition_query=True))
        elif ws_filter:
            # Fetch per workspace (partition key queries)
            events = []
            for wid in ws_filter:
                query = "SELECT * FROM c WHERE c.workspace_id = @wid AND c.timestamp >= @cutoff"
                params = [
                    {"name": "@wid", "value": wid},
                    {"name": "@cutoff", "value": cutoff},
                ]
                events.extend(list(container.query_items(query=query, parameters=params, partition_key=wid)))
        else:
            events = []
    except Exception:
        events = []

    # Aggregate
    total_queries = len(events)
    total_tokens = sum(e.get("tokens_used", 0) for e in events)
    total_cost = sum(e.get("cost_usd", 0.0) for e in events)
    avg_duration = (
        sum(e.get("duration_ms", 0) for e in events) / total_queries
        if total_queries > 0 else 0
    )
    unique_users = len(set(e.get("user_email", "") for e in events))

    # Daily breakdown
    daily: dict[str, dict] = {}
    for e in events:
        day = e.get("timestamp", "")[:10]
        if day not in daily:
            daily[day] = {"date": day, "queries": 0, "tokens": 0, "cost": 0.0, "users": set()}
        daily[day]["queries"] += 1
        daily[day]["tokens"] += e.get("tokens_used", 0)
        daily[day]["cost"] += e.get("cost_usd", 0.0)
        daily[day]["users"].add(e.get("user_email", ""))

    daily_trends = sorted([
        {"date": d["date"], "queries": d["queries"], "tokens": d["tokens"],
         "cost": round(d["cost"], 4), "unique_users": len(d["users"])}
        for d in daily.values()
    ], key=lambda x: x["date"])

    # Per-user breakdown
    user_activity: dict[str, dict] = {}
    for e in events:
        email = e.get("user_email", "unknown")
        if email not in user_activity:
            user_activity[email] = {"email": email, "queries": 0, "tokens": 0, "cost": 0.0}
        user_activity[email]["queries"] += 1
        user_activity[email]["tokens"] += e.get("tokens_used", 0)
        user_activity[email]["cost"] += e.get("cost_usd", 0.0)

    top_users = sorted(user_activity.values(), key=lambda u: u["queries"], reverse=True)[:20]
    for u in top_users:
        u["cost"] = round(u["cost"], 4)

    # Analysis mode distribution
    mode_dist: dict[str, int] = {}
    for e in events:
        mode = e.get("analysis_mode", "quick")
        mode_dist[mode] = mode_dist.get(mode, 0) + 1

    # Model usage
    model_dist: dict[str, int] = {}
    for e in events:
        model = e.get("model_name", "unknown")
        if model:
            model_dist[model] = model_dist.get(model, 0) + 1

    return {
        "period": period,
        "total_queries": total_queries,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 4),
        "avg_duration_ms": round(avg_duration, 1),
        "unique_users": unique_users,
        "daily_trends": daily_trends,
        "top_users": top_users,
        "mode_distribution": mode_dist,
        "model_distribution": model_dist,
    }
