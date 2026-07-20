from __future__ import annotations

import asyncio
import html
import logging
import re
import time
import uuid
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agent.graph import run_agent
from app.config import settings
from app.db.insight_db import insight_db
from app.services.email_service import send_alert_email

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
CRON_ADVISORY_LOCK_ID = 124_708_401
_runner_task: asyncio.Task | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_doc(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def normalize_email_list(emails: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in emails:
        email = (value or "").strip().lower()
        if email and EMAIL_RE.fullmatch(email) and email not in seen:
            seen.add(email)
            normalized.append(email)
    return normalized


def extract_prompt_emails(prompt: str) -> list[str]:
    return normalize_email_list(EMAIL_RE.findall(prompt or ""))


def build_analysis_prompt(prompt_text: str, user_doc: dict) -> str:
    """Strip delivery instructions before handing the request to the data agent."""
    cleaned = EMAIL_RE.sub("", prompt_text or "")
    cleaned = re.sub(r"^\s*(please\s+)?(send|email|mail|forward)\s+me\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*(please\s+)?(send|email|mail|forward)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+\b(to|on|at)\s*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\b(send|email|mail|forward)\s+(me\s+)?(this|it|the report|the data)?\s*(to|on|at)?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-")
    if not cleaned:
        cleaned = "Generate the requested scheduled report."

    role = user_doc.get("role", "user")
    scope_note = (
        "The schedule owner is a privileged user. If no customer, user, or account is named, "
        "query all available data in the selected workspace."
        if role in ("admin", "manager", "moderator")
        else "The schedule owner is a locked user. Use only the server-enforced customer scope for this user."
    )

    return (
        "This is an automated scheduled DataLens report. "
        "Email delivery is handled by the scheduler outside the analytics agent, so do not say that you cannot send email. "
        f"{scope_note}\n\n"
        f"Report request: {cleaned}"
    )


def calculate_next_execution(
    schedule_time: str,
    schedule_days: list[str] | None,
    schedule_timezone: str,
    *,
    from_dt: datetime | None = None,
) -> str:
    try:
        hour, minute = [int(part) for part in schedule_time.split(":", 1)]
        local_time = dt_time(hour=hour, minute=minute)
    except Exception as exc:
        raise ValueError("schedule_time must be HH:MM") from exc

    days = [d.lower() for d in (schedule_days or list(WEEKDAYS)) if d.lower() in WEEKDAYS]
    if not days:
        days = list(WEEKDAYS)

    try:
        tz = ZoneInfo(schedule_timezone or "Asia/Kolkata")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Kolkata")

    now = from_dt or datetime.now(timezone.utc)
    local_now = now.astimezone(tz)
    allowed = {WEEKDAYS.index(day) for day in days}

    for offset in range(8):
        candidate_date = local_now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in allowed:
            continue
        candidate_local = datetime.combine(candidate_date, local_time, tzinfo=tz)
        if candidate_local > local_now:
            return candidate_local.astimezone(timezone.utc).isoformat()

    raise ValueError("Could not calculate next execution")


async def execute_due_scheduled_prompts(limit: int = 25) -> dict:
    if not insight_db.is_ready:
        raise RuntimeError("Persistence not configured")

    pool = getattr(insight_db, "_pool", None)
    if pool is None:
        raise RuntimeError("Persistence pool not available")

    start = time.perf_counter()
    results: list[dict] = []

    with pool.connection() as lock_conn:
        locked = bool(
            lock_conn.execute(
                "SELECT pg_try_advisory_lock(%s)",
                (CRON_ADVISORY_LOCK_ID,),
            ).fetchone()[0]
        )
        if not locked:
            return {"success": True, "skipped": True, "reason": "another-run-in-progress"}

        try:
            now = utc_now_iso()
            prompts = list(
                insight_db.container("scheduled_prompts").query_items(
                    query=(
                        "SELECT * FROM c WHERE c.is_active = true "
                        "AND c.next_execution_at != '' AND c.next_execution_at <= @now "
                        "ORDER BY c.next_execution_at"
                    ),
                    parameters=[{"name": "@now", "value": now}],
                    enable_cross_partition_query=True,
                )
            )[:limit]

            for prompt in prompts:
                results.append(await execute_scheduled_prompt(prompt))
        finally:
            try:
                lock_conn.execute("SELECT pg_advisory_unlock(%s)", (CRON_ADVISORY_LOCK_ID,))
            except Exception:
                logger.exception("Failed to release scheduled prompt advisory lock")

    return {
        "success": True,
        "executed": len(results),
        "total_time_ms": round((time.perf_counter() - start) * 1000, 2),
        "results": results,
    }


def start_scheduled_prompt_runner() -> None:
    global _runner_task
    if not settings.scheduled_prompts_runner_enabled:
        logger.info("Scheduled prompt runner disabled")
        return
    if _runner_task and not _runner_task.done():
        return
    _runner_task = asyncio.create_task(_scheduled_prompt_runner_loop())
    logger.info(
        "Scheduled prompt runner started: interval=%ss",
        settings.scheduled_prompts_runner_interval_seconds,
    )


async def stop_scheduled_prompt_runner() -> None:
    global _runner_task
    if not _runner_task:
        return
    _runner_task.cancel()
    try:
        await _runner_task
    except asyncio.CancelledError:
        pass
    _runner_task = None
    logger.info("Scheduled prompt runner stopped")


async def _scheduled_prompt_runner_loop() -> None:
    interval = max(15, int(settings.scheduled_prompts_runner_interval_seconds or 60))
    while True:
        try:
            if insight_db.is_ready:
                result = await execute_due_scheduled_prompts()
                if result.get("executed"):
                    logger.info("Scheduled prompt runner executed %s prompt(s)", result["executed"])
            else:
                logger.debug("Scheduled prompt runner waiting for persistence")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled prompt runner tick failed")

        await asyncio.sleep(interval)


async def execute_scheduled_prompt(prompt: dict) -> dict:
    started = time.perf_counter()
    prompt_id = prompt["id"]
    user_id = prompt.get("user_id", "")
    executions = insight_db.container("scheduled_prompt_executions")
    schedules = insight_db.container("scheduled_prompts")

    try:
        user_doc = _fetch_user(user_id)
        customer_scope = ""
        customer_scope_name = ""
        customer_scope_field = "customer_id"
        if user_doc.get("role") not in ("admin", "manager", "moderator") and user_doc.get("customer_code"):
            customer_scope = user_doc["customer_code"]
            customer_scope_name = user_doc["customer_code"]
            customer_scope_field = "customer_code"

        analysis_prompt = build_analysis_prompt(prompt.get("prompt_text", ""), user_doc)
        result = await run_agent(
            question=analysis_prompt,
            connection_id=prompt.get("connection_id", ""),
            workspace_id=prompt.get("workspace_id", ""),
            analysis_mode=prompt.get("analysis_mode") or "quick",
            user_id=user_id,
            customer_scope=customer_scope,
            customer_scope_name=customer_scope_name,
            customer_scope_field=customer_scope_field,
        )
        response_text = insight_to_text(result or {})
        recipients = (
            extract_prompt_emails(prompt.get("prompt_text", ""))
            or normalize_email_list(prompt.get("email_recipients") or [])
            or normalize_email_list([user_doc.get("email", "")])
        )

        email_sent = False
        email_error = ""
        if recipients:
            try:
                await asyncio.to_thread(
                    send_alert_email,
                    to=recipients,
                    subject=prompt.get("email_subject") or f"Scheduled Report: {prompt.get('name') or 'DataLens'}",
                    body_html=insight_to_email_html(result or {}, prompt.get("name") or "Scheduled Report"),
                )
                email_sent = True
            except Exception as exc:
                email_error = str(exc)
                logger.exception("Scheduled prompt email failed: prompt_id=%s", prompt_id)

        execution_time_ms = round((time.perf_counter() - started) * 1000, 2)
        executions.create_item(
            {
                "id": uuid.uuid4().hex[:12],
                "scheduled_prompt_id": prompt_id,
                "user_id": user_id,
                "status": "success",
                "response": response_text[:20000],
                "email_sent": email_sent,
                "email_error": email_error,
                "error_message": "",
                "execution_time_ms": execution_time_ms,
                "created_at": utc_now_iso(),
            }
        )

        prompt["last_executed_at"] = utc_now_iso()
        prompt["next_execution_at"] = calculate_next_execution(
            prompt.get("schedule_time", "22:00"),
            prompt.get("schedule_days") or list(WEEKDAYS),
            prompt.get("schedule_timezone") or "Asia/Kolkata",
        )
        prompt["updated_at"] = utc_now_iso()
        schedules.upsert_item(prompt)

        return {
            "prompt_id": prompt_id,
            "prompt_name": prompt.get("name", ""),
            "status": "success",
            "email_sent": email_sent,
            "email_error": email_error,
        }
    except Exception as exc:
        logger.exception("Scheduled prompt execution failed: prompt_id=%s", prompt_id)
        execution_time_ms = round((time.perf_counter() - started) * 1000, 2)
        executions.create_item(
            {
                "id": uuid.uuid4().hex[:12],
                "scheduled_prompt_id": prompt_id,
                "user_id": user_id,
                "status": "failed",
                "response": "",
                "email_sent": False,
                "email_error": "",
                "error_message": str(exc),
                "execution_time_ms": execution_time_ms,
                "created_at": utc_now_iso(),
            }
        )
        try:
            prompt["next_execution_at"] = calculate_next_execution(
                prompt.get("schedule_time", "22:00"),
                prompt.get("schedule_days") or list(WEEKDAYS),
                prompt.get("schedule_timezone") or "Asia/Kolkata",
            )
            prompt["updated_at"] = utc_now_iso()
            schedules.upsert_item(prompt)
        except Exception:
            logger.exception("Failed to advance failed scheduled prompt: prompt_id=%s", prompt_id)

        return {
            "prompt_id": prompt_id,
            "prompt_name": prompt.get("name", ""),
            "status": "failed",
            "error": str(exc),
        }


async def test_scheduled_prompt(prompt: dict, user_doc: dict | None = None) -> dict:
    """Run a scheduled prompt immediately without sending email or advancing schedule."""
    started = time.perf_counter()
    prompt_id = prompt.get("id") or "draft"
    user_id = prompt.get("user_id", "")

    try:
        owner_doc = user_doc or _fetch_user(user_id)
        customer_scope = ""
        customer_scope_name = ""
        customer_scope_field = "customer_id"
        if owner_doc.get("role") not in ("admin", "manager", "moderator") and owner_doc.get("customer_code"):
            customer_scope = owner_doc["customer_code"]
            customer_scope_name = owner_doc["customer_code"]
            customer_scope_field = "customer_code"

        analysis_prompt = build_analysis_prompt(prompt.get("prompt_text", ""), owner_doc)
        result = await run_agent(
            question=analysis_prompt,
            connection_id=prompt.get("connection_id", ""),
            workspace_id=prompt.get("workspace_id", ""),
            analysis_mode=prompt.get("analysis_mode") or "quick",
            user_id=user_id,
            customer_scope=customer_scope,
            customer_scope_name=customer_scope_name,
            customer_scope_field=customer_scope_field,
        )
        response_text = insight_to_text(result or {})
        return {
            "prompt_id": prompt_id,
            "prompt_name": prompt.get("name", ""),
            "status": "success",
            "response": response_text[:20000],
            "email_sent": False,
            "email_error": "",
            "error_message": "",
            "execution_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "created_at": utc_now_iso(),
        }
    except Exception as exc:
        logger.exception("Scheduled prompt test failed: prompt_id=%s", prompt_id)
        return {
            "prompt_id": prompt_id,
            "prompt_name": prompt.get("name", ""),
            "status": "failed",
            "response": "",
            "email_sent": False,
            "email_error": "",
            "error_message": str(exc),
            "execution_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "created_at": utc_now_iso(),
        }


def _fetch_user(user_id: str) -> dict:
    users = insight_db.container("users")
    rows = list(
        users.query_items(
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": user_id}],
            enable_cross_partition_query=True,
        )
    )
    if not rows:
        raise ValueError("Scheduled prompt owner not found")
    return clean_doc(rows[0])


def insight_to_text(result: dict) -> str:
    parts: list[str] = []
    summary_text = summary_to_text(result.get("summary"))
    if summary_text:
        parts.append(summary_text)

    for table in result.get("tables") or []:
        title = table.get("title") or "Table"
        columns = table.get("columns") or []
        rows = table.get("data") or []
        if not columns or not rows:
            continue
        parts.append(f"\n{title}")
        parts.append(" | ".join(str(c) for c in columns))
        parts.append(" | ".join("---" for _ in columns))
        for row in rows[:50]:
            parts.append(" | ".join(str(row.get(c, "")) for c in columns))

    return "\n".join(parts).strip() or "The scheduled prompt completed, but no report content was generated."


def summary_to_text(summary: object) -> str:
    if not summary:
        return ""
    if isinstance(summary, str):
        return summary
    if not isinstance(summary, dict):
        return str(summary)

    parts: list[str] = []
    title = str(summary.get("title") or "").strip()
    narrative = str(summary.get("narrative") or "").strip()
    if title:
        parts.append(title)
    if narrative:
        parts.append(narrative)

    findings = summary.get("key_findings") or []
    if isinstance(findings, list) and findings:
        parts.append("Key findings:")
        for finding in findings:
            if isinstance(finding, dict):
                headline = str(finding.get("headline") or "").strip()
                detail = str(finding.get("detail") or "").strip()
                if headline and detail:
                    parts.append(f"- {headline}: {detail}")
                elif headline or detail:
                    parts.append(f"- {headline or detail}")

    return "\n".join(parts).strip()


def insight_to_email_html(result: dict, prompt_name: str) -> str:
    summary_text = summary_to_text(result.get("summary")) or "Scheduled report completed."
    body = [
        "<div style='white-space: pre-wrap; line-height: 1.6;'>"
        f"{html.escape(summary_text)}"
        "</div>"
    ]
    for table in result.get("tables") or []:
        columns = table.get("columns") or []
        rows = table.get("data") or []
        if not columns or not rows:
            continue
        header = "".join(f"<th>{html.escape(str(col))}</th>" for col in columns)
        body_rows = []
        for row in rows[:100]:
            cells = "".join(f"<td>{html.escape(str(row.get(col, '')))}</td>" for col in columns)
            body_rows.append(f"<tr>{cells}</tr>")
        body.append(
            f"<h3>{html.escape(str(table.get('title') or 'Table'))}</h3>"
            f"<table>{'<thead><tr>' + header + '</tr></thead>'}<tbody>{''.join(body_rows)}</tbody></table>"
        )

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 900px; margin: 0 auto; color: #111827;">
      <div style="background: #111827; color: white; padding: 24px;">
        <h1 style="margin: 0; font-size: 22px;">DataLens Scheduled Report</h1>
        <p style="margin: 8px 0 0; color: #d1d5db;">{html.escape(prompt_name)}</p>
      </div>
      <div style="border: 1px solid #e5e7eb; border-top: 0; padding: 24px;">
        <style>
          table {{ width: 100%; border-collapse: collapse; margin: 16px 0 24px; }}
          th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #e5e7eb; font-size: 13px; }}
          th {{ background: #f9fafb; font-weight: 700; }}
          h3 {{ margin: 24px 0 8px; font-size: 16px; }}
        </style>
        {''.join(body)}
        <p style="margin-top: 28px; color: #6b7280; font-size: 12px;">Generated on {html.escape(datetime.now(timezone.utc).isoformat())} UTC</p>
      </div>
    </div>
    """
