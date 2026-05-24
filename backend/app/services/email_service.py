import io
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import openpyxl

from app.config import settings

_SKIP_CHART_TYPES = {"kpi", "gauge"}


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
    msg = MIMEMultipart()
    msg["From"] = settings.email_smtp_from
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
        server.sendmail(settings.email_smtp_from, to, msg.as_string())


def _sanitize_sheet_name(name: str) -> str:
    """Remove chars Excel forbids in sheet names and cap at 31 characters."""
    cleaned = name.translate(str.maketrans("", "", r'\/?*[]:' )).strip()
    return (cleaned or "Sheet")[:31]
