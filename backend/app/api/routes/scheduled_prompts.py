from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.routes.persistence import _fetch_workspace, _verify_workspace_access
from app.api.routes.users import get_current_user
from app.config import settings
from app.db.insight_db import insight_db
from app.services.scheduled_prompt_service import (
    WEEKDAYS,
    calculate_next_execution,
    clean_doc,
    execute_due_scheduled_prompts,
    normalize_email_list,
    test_scheduled_prompt,
    utc_now_iso,
)

router = APIRouter(prefix="/api/scheduled-prompts", tags=["scheduled-prompts"])


class ScheduledPromptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt_text: str = Field(min_length=5, max_length=5000)
    workspace_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    analysis_mode: str = "quick"
    email_recipients: list[str] = []
    email_subject: str = ""
    schedule_time: str = "22:00"
    schedule_timezone: str = "Asia/Kolkata"
    schedule_days: list[str] = list(WEEKDAYS)


class ScheduledPromptUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    prompt_text: str | None = Field(default=None, min_length=5, max_length=5000)
    workspace_id: str | None = None
    connection_id: str | None = None
    analysis_mode: str | None = None
    email_recipients: list[str] | None = None
    email_subject: str | None = None
    schedule_time: str | None = None
    schedule_timezone: str | None = None
    schedule_days: list[str] | None = None
    is_active: bool | None = None


class ScheduledPromptTestRequest(BaseModel):
    name: str = Field(default="Draft scheduled prompt", min_length=1, max_length=120)
    prompt_text: str = Field(min_length=5, max_length=5000)
    workspace_id: str = Field(min_length=1)
    connection_id: str = Field(min_length=1)
    analysis_mode: str = "quick"


def _require_db() -> None:
    if not insight_db.is_ready:
        raise HTTPException(status_code=503, detail="Persistence not configured")


def _container():
    return insight_db.container("scheduled_prompts")


def _fetch_prompt(prompt_id: str) -> dict:
    rows = list(
        _container().query_items(
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": prompt_id}],
            enable_cross_partition_query=True,
        )
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Scheduled prompt not found")
    return rows[0]


def _verify_prompt_access(prompt: dict, current_user: dict) -> None:
    if current_user.get("role") == "admin":
        return
    if prompt.get("user_id") != current_user.get("id"):
        raise HTTPException(status_code=403, detail="Access denied")


def _validate_workspace_connection(workspace_id: str, connection_id: str, current_user: dict) -> None:
    ws = _fetch_workspace(workspace_id)
    _verify_workspace_access(ws, current_user)
    connection_ids = set(ws.get("connection_ids") or [])
    for conn in ws.get("connections") or []:
        if isinstance(conn, dict) and conn.get("id"):
            connection_ids.add(conn["id"])
    if connection_id not in connection_ids:
        raise HTTPException(status_code=400, detail="Connection does not belong to this workspace")


def _clean_schedule_days(days: list[str]) -> list[str]:
    cleaned = [day.lower() for day in days if day.lower() in WEEKDAYS]
    return cleaned or list(WEEKDAYS)


async def _get_scheduler_user(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Admin or manager access required")
    return current_user


@router.get("")
async def list_scheduled_prompts(current_user: dict = Depends(_get_scheduler_user)):
    _require_db()
    if current_user.get("role") == "admin":
        rows = list(
            _container().query_items(
                query="SELECT * FROM c ORDER BY c.created_at DESC",
                enable_cross_partition_query=True,
            )
        )
    else:
        rows = list(
            _container().query_items(
                query="SELECT * FROM c WHERE c.user_id = @uid ORDER BY c.created_at DESC",
                parameters=[{"name": "@uid", "value": current_user.get("id", "")}],
                enable_cross_partition_query=True,
            )
        )
    return [clean_doc(row) for row in rows]


@router.post("")
async def create_scheduled_prompt(
    data: ScheduledPromptCreate,
    current_user: dict = Depends(_get_scheduler_user),
):
    _require_db()
    _validate_workspace_connection(data.workspace_id, data.connection_id, current_user)
    schedule_days = _clean_schedule_days(data.schedule_days)
    doc = {
        "id": f"sp-{uuid.uuid4().hex[:10]}",
        "user_id": current_user.get("id", ""),
        "workspace_id": data.workspace_id,
        "connection_id": data.connection_id,
        "name": data.name.strip(),
        "prompt_text": data.prompt_text.strip(),
        "analysis_mode": data.analysis_mode if data.analysis_mode in ("quick", "deep") else "quick",
        "email_recipients": normalize_email_list(data.email_recipients),
        "email_subject": data.email_subject.strip(),
        "schedule_time": data.schedule_time,
        "schedule_timezone": data.schedule_timezone.strip() or "Asia/Kolkata",
        "schedule_days": schedule_days,
        "is_active": True,
        "last_executed_at": "",
        "next_execution_at": calculate_next_execution(
            data.schedule_time,
            schedule_days,
            data.schedule_timezone,
        ),
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    _container().create_item(doc)
    return clean_doc(doc)


@router.put("/{prompt_id}")
async def update_scheduled_prompt(
    prompt_id: str,
    data: ScheduledPromptUpdate,
    current_user: dict = Depends(_get_scheduler_user),
):
    _require_db()
    existing = _fetch_prompt(prompt_id)
    _verify_prompt_access(existing, current_user)

    updates = data.model_dump(exclude_unset=True)
    workspace_id = updates.get("workspace_id", existing.get("workspace_id", ""))
    connection_id = updates.get("connection_id", existing.get("connection_id", ""))
    if "workspace_id" in updates or "connection_id" in updates:
        _validate_workspace_connection(workspace_id, connection_id, current_user)

    for key, value in updates.items():
        if key == "email_recipients" and value is not None:
            existing[key] = normalize_email_list(value)
        elif key == "schedule_days" and value is not None:
            existing[key] = _clean_schedule_days(value)
        elif key == "analysis_mode" and value is not None:
            existing[key] = value if value in ("quick", "deep") else "quick"
        elif value is not None:
            existing[key] = value.strip() if isinstance(value, str) else value

    existing["next_execution_at"] = calculate_next_execution(
        existing.get("schedule_time", "22:00"),
        existing.get("schedule_days") or list(WEEKDAYS),
        existing.get("schedule_timezone") or "Asia/Kolkata",
    )
    existing["updated_at"] = utc_now_iso()
    _container().upsert_item(existing)
    return clean_doc(existing)


@router.delete("/{prompt_id}", status_code=204)
async def delete_scheduled_prompt(
    prompt_id: str,
    current_user: dict = Depends(_get_scheduler_user),
):
    _require_db()
    existing = _fetch_prompt(prompt_id)
    _verify_prompt_access(existing, current_user)
    _container().delete_item(prompt_id)


@router.get("/{prompt_id}/executions")
async def list_executions(
    prompt_id: str,
    current_user: dict = Depends(_get_scheduler_user),
):
    _require_db()
    existing = _fetch_prompt(prompt_id)
    _verify_prompt_access(existing, current_user)
    rows = list(
        insight_db.container("scheduled_prompt_executions").query_items(
            query=(
                "SELECT * FROM c WHERE c.scheduled_prompt_id = @id "
                "ORDER BY c.created_at DESC"
            ),
            parameters=[{"name": "@id", "value": prompt_id}],
            enable_cross_partition_query=True,
        )
    )
    return [clean_doc(row) for row in rows[:25]]


@router.post("/test")
async def test_draft_scheduled_prompt(
    data: ScheduledPromptTestRequest,
    current_user: dict = Depends(_get_scheduler_user),
):
    _require_db()
    _validate_workspace_connection(data.workspace_id, data.connection_id, current_user)
    prompt = {
        "id": "draft",
        "user_id": current_user.get("id", ""),
        "workspace_id": data.workspace_id,
        "connection_id": data.connection_id,
        "name": data.name.strip(),
        "prompt_text": data.prompt_text.strip(),
        "analysis_mode": data.analysis_mode if data.analysis_mode in ("quick", "deep") else "quick",
    }
    return await test_scheduled_prompt(prompt, current_user)


@router.post("/{prompt_id}/test")
async def test_existing_scheduled_prompt(
    prompt_id: str,
    current_user: dict = Depends(_get_scheduler_user),
):
    _require_db()
    existing = _fetch_prompt(prompt_id)
    _verify_prompt_access(existing, current_user)
    _validate_workspace_connection(
        existing.get("workspace_id", ""),
        existing.get("connection_id", ""),
        current_user,
    )
    return await test_scheduled_prompt(existing)


@router.post("/cron/execute-due")
async def execute_due(
    authorization: str | None = Header(default=None),
    cron_secret: str = Query(default=""),
):
    if settings.scheduled_prompts_cron_secret:
        supplied = cron_secret or ""
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization[7:]
        if supplied != settings.scheduled_prompts_cron_secret:
            raise HTTPException(status_code=401, detail="Invalid cron secret")
    else:
        current_user = await get_current_user(authorization=authorization)
        if current_user.get("role") not in ("admin", "manager"):
            raise HTTPException(status_code=403, detail="Admin or manager access required")

    _require_db()
    return await execute_due_scheduled_prompts()
