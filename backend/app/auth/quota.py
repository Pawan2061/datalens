from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.auth.user_doc_cache import set_cached_user_doc
from app.config import settings
from app.db.insight_db import insight_db
from app.schemas.persistence import QuotaCheckResult, UsageRecord

logger = logging.getLogger(__name__)

# Holds references to in-flight alert email tasks so they aren't garbage
# collected before they finish (asyncio only keeps weak refs to tasks).
_alert_tasks: set[asyncio.Task] = set()


def _fire_cost_alert(doc: dict) -> None:
    """Send the one-time cost-alert email to the team, without blocking.

    SMTP is synchronous, so it runs in a worker thread via asyncio.to_thread.
    Fully guarded — an email failure must never break usage recording.
    """
    try:
        from app.services.email_service import send_alert_email

        name = doc.get("name") or "(no name)"
        email = doc.get("email") or "(no email)"
        user_id = doc.get("id") or "(unknown)"
        spend = doc.get("total_cost_usd", 0.0)
        threshold = settings.cost_alert_threshold_usd
        recipients = list(settings.cost_alert_recipients)

        subject = f"[DataLens] Usage alert: {name} crossed ${threshold:.2f}"
        body_html = (
            "<p>Hello team,</p>"
            f"<p>A DataLens user has crossed the <b>${threshold:.2f}</b> "
            "cumulative usage threshold.</p>"
            "<ul>"
            f"<li><b>Name:</b> {name}</li>"
            f"<li><b>Email:</b> {email}</li>"
            f"<li><b>User ID:</b> {user_id}</li>"
            f"<li><b>Total spend to date:</b> ${spend:.4f}</li>"
            "</ul>"
            "<p>This is an automated, informational notice — the user has not "
            "been blocked. You may review their activity in the admin dashboard "
            "if any action is needed.</p>"
            "<p>— DataLens</p>"
        )

        async def _send():
            try:
                await asyncio.to_thread(
                    send_alert_email,
                    to=recipients,
                    subject=subject,
                    body_html=body_html,
                )
                logger.info("Cost-alert email sent for user=%s ($%.4f)", user_id, spend)
            except Exception as exc:
                logger.warning("Failed to send cost-alert email for user=%s: %s", user_id, exc)

        task = asyncio.create_task(_send())
        _alert_tasks.add(task)
        task.add_done_callback(_alert_tasks.discard)
    except Exception as exc:
        logger.warning("Could not schedule cost-alert email: %s", exc)


async def check_quota(user_doc: dict) -> QuotaCheckResult:
    """Check if user can make a request based on their limits."""
    # Admins bypass quota checks
    if user_doc.get("role") == "admin":
        return QuotaCheckResult(allowed=True)

    # Check expiry
    expiry = user_doc.get("expiry_date", "")
    if expiry:
        try:
            expiry_dt = datetime.fromisoformat(expiry)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            if expiry_dt < datetime.now(timezone.utc):
                return QuotaCheckResult(
                    allowed=False,
                    reason="Your access has expired. Contact admin.",
                )
        except (ValueError, TypeError):
            pass

    # Check daily question limit
    max_q = user_doc.get("max_questions_per_day", 0)
    today_q = user_doc.get("today_questions", 0)
    if max_q > 0 and today_q >= max_q:
        return QuotaCheckResult(
            allowed=False,
            reason=f"Daily question limit reached ({max_q}). Resets tomorrow.",
        )

    # Check daily token limit
    max_t = user_doc.get("max_tokens_per_day", 0)
    today_t = user_doc.get("today_tokens", 0)
    if max_t > 0 and today_t >= max_t:
        return QuotaCheckResult(
            allowed=False,
            reason=f"Daily token limit reached ({max_t:,}).",
        )

    # Check monthly cost limit
    max_c = user_doc.get("max_cost_usd_per_month", 0.0)
    month_c = user_doc.get("month_cost_usd", 0.0)
    if max_c > 0 and month_c >= max_c:
        return QuotaCheckResult(
            allowed=False,
            reason=f"Monthly cost limit reached (${max_c:.2f}).",
        )

    return QuotaCheckResult(
        allowed=True,
        remaining_questions=max_q - today_q if max_q > 0 else -1,
        remaining_tokens=max_t - today_t if max_t > 0 else -1,
        remaining_cost_usd=round(max_c - month_c, 4) if max_c > 0 else -1.0,
    )


async def record_usage(
    user_id: str,
    total_tokens: int,
    cost_usd: float,
    questions: int = 1,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    model_name: str = "",
) -> None:
    """Update user's usage counters after a request and write a usage log."""
    if not insight_db.is_ready:
        return

    users = insight_db.container("users")
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_str = datetime.now(timezone.utc).strftime("%Y-%m")

    # Find the user
    query = "SELECT * FROM c WHERE c.id = @id"
    params = [{"name": "@id", "value": user_id}]
    results = list(
        users.query_items(
            query=query, parameters=params, enable_cross_partition_query=True
        )
    )
    if not results:
        return

    doc = results[0]

    # Reset daily counters if usage_reset_date != today
    if doc.get("usage_reset_date", "") != today_str:
        doc["today_questions"] = 0
        doc["today_tokens"] = 0
        doc["today_cost_usd"] = 0.0
        doc["usage_reset_date"] = today_str

    # Reset monthly cost if month_reset_date != this month
    if doc.get("month_reset_date", "") != month_str:
        doc["month_cost_usd"] = 0.0
        doc["month_reset_date"] = month_str

    # Increment counters
    doc["today_questions"] = doc.get("today_questions", 0) + questions
    doc["today_tokens"] = doc.get("today_tokens", 0) + total_tokens
    doc["today_cost_usd"] = round(doc.get("today_cost_usd", 0.0) + cost_usd, 6)
    doc["month_cost_usd"] = round(doc.get("month_cost_usd", 0.0) + cost_usd, 6)
    doc["total_questions"] = doc.get("total_questions", 0) + questions
    doc["total_tokens"] = doc.get("total_tokens", 0) + total_tokens
    doc["total_cost_usd"] = round(doc.get("total_cost_usd", 0.0) + cost_usd, 6)

    # ── Cost alert: email the team once a user's cumulative lifetime spend
    # first crosses the threshold. Alert-only — the user is not blocked. The
    # flag is set on the doc BEFORE upsert so it persists and the email fires
    # exactly once; if SMTP is flaky this means at most one missed alert
    # (acceptable, and we never retry-spam). No-op unless SMTP + recipients
    # are configured.
    threshold = settings.cost_alert_threshold_usd
    if (
        threshold > 0
        and doc.get("total_cost_usd", 0.0) >= threshold
        and not doc.get("cost_alert_2usd_sent", False)
        and settings.cost_alert_recipients
        and settings.email_smtp_user
    ):
        doc["cost_alert_2usd_sent"] = True
        _fire_cost_alert(doc)

    users.upsert_item(doc)
    set_cached_user_doc(user_id, doc)

    # Write usage log entry
    try:
        usage_logs = insight_db.container("usage_logs")
        log = UsageRecord(
            user_id=user_id,
            questions=questions,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            model_name=model_name,
        )
        usage_logs.create_item(log.model_dump())
    except Exception as exc:
        # Don't fail the request if logging fails, but surface the reason —
        # a silent `pass` here previously hid a schema/column mismatch for weeks.
        logger.warning("Failed to write usage_logs entry for user=%s: %s", user_id, exc)
