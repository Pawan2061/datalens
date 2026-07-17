import io
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr

import openpyxl

from app.config import settings

_SKIP_CHART_TYPES = {"kpi", "gauge"}
_EMAIL_IN_TEXT_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def build_excel_bytes(tables: list[dict], charts: list[dict]) -> bytes | None:
    """Build an xlsx workbook from InsightResult tables and chart data.

    Returns raw bytes, or None if there is nothing exportable.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # discard the default empty sheet

    for i, table in enumerate(tables):
        title = _sanitize_sheet_name(table.get("title") or f"Table {i + 1}")
        ws = wb.create_sheet(title=title)
        cols: list[str] = table.get("columns") or []
        ws.append(cols)
        for row in table.get("data") or []:
            ws.append([row.get(c) for c in cols])

    for i, chart in enumerate(charts):
        if chart.get("chart_type") in _SKIP_CHART_TYPES:
            continue
        rows: list[dict] = chart.get("data") or []
        if not rows:
            continue
        cols = list(rows[0].keys())
        title = _sanitize_sheet_name(chart.get("title") or f"Chart {i + 1}")
        ws = wb.create_sheet(title=title)
        ws.append(cols)
        for row in rows:
            ws.append([row.get(c) for c in cols])

    if not wb.sheetnames:
        return None

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def send_excel_email(
    *,
    to: str,
    subject: str,
    body_html: str,
    excel_bytes: bytes,
    filename: str,
) -> None:
    """Send an email with an xlsx attachment using the configured SMTP settings."""
    header_from, envelope_from = _smtp_from_values()
    msg = MIMEMultipart()
    msg["From"] = header_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    part = MIMEBase(
        "application",
        "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    part.set_payload(excel_bytes)
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port) as server:
        server.starttls()
        server.login(settings.email_smtp_user, settings.email_smtp_pass)
        server.sendmail(envelope_from, to, msg.as_string())


def send_alert_email(*, to: list[str], subject: str, body_html: str) -> None:
    """Send a plain HTML alert email (no attachment) to one or more recipients.

    Uses the same SMTP settings/flow as send_excel_email(). Blocking — call
    from a thread (asyncio.to_thread) when on the event loop.
    """
    header_from, envelope_from = _smtp_from_values()
    msg = MIMEMultipart()
    msg["From"] = header_from
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html"))

    with smtplib.SMTP(settings.email_smtp_host, settings.email_smtp_port) as server:
        server.starttls()
        server.login(settings.email_smtp_user, settings.email_smtp_pass)
        server.sendmail(envelope_from, to, msg.as_string())


def _smtp_from_values() -> tuple[str, str]:
    """Return RFC-safe header From plus plain envelope sender for SMTP MAIL FROM.

    Gmail requires the envelope sender to be the authenticated mailbox (or an
    explicitly allowed alias). Keep EMAIL_SMTP_USER as the authoritative SMTP
    sender and treat EMAIL_SMTP_FROM as an optional display/header value only.
    """
    user_email = (settings.email_smtp_user or "").strip()
    raw_from = (settings.email_smtp_from or settings.email_smtp_user or "").strip()
    display_name, parsed_email = parseaddr(raw_from)
    extracted = _EMAIL_IN_TEXT_RE.search(raw_from)
    email_addr = parsed_email if _EMAIL_IN_TEXT_RE.fullmatch(parsed_email or "") else ""
    email_addr = email_addr or (extracted.group(0) if extracted else raw_from)
    envelope_from = user_email or email_addr
    if display_name and envelope_from:
        return formataddr((display_name, envelope_from)), envelope_from
    return envelope_from, envelope_from


def _sanitize_sheet_name(name: str) -> str:
    """Remove chars Excel forbids in sheet names and cap at 31 characters."""
    cleaned = name.translate(str.maketrans("", "", r'\/?*[]:' )).strip()
    return (cleaned or "Sheet")[:31]
