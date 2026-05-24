import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.email_service import build_excel_bytes, send_excel_email

router = APIRouter(prefix="/api/email", tags=["email"])

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


class SendDataRequest(BaseModel):
    to_email: str
    insight_title: str
    tables: list[dict]
    charts: list[dict]


@router.post("/send-data", status_code=200)
async def send_data(req: SendDataRequest):
    if not _EMAIL_RE.match(req.to_email):
        raise HTTPException(status_code=400, detail="Invalid email address")

    excel_bytes = build_excel_bytes(req.tables, req.charts)
    if excel_bytes is None:
        raise HTTPException(status_code=400, detail="No exportable data in the response")

    title = (req.insight_title or "DataLens Export")[:60]
    safe_name = re.sub(r"[^a-zA-Z0-9_\- ]", "", title).strip().replace(" ", "_")[:40]
    subject = f"DataLens Export: {title}"
    body = (
        "<p>Hello,</p>"
        "<p>Please find your exported data attached from the DataLens query: "
        f"<strong>{title}</strong></p>"
        "<p>— DataLens Analytics</p>"
    )

    try:
        send_excel_email(
            to=req.to_email,
            subject=subject,
            body_html=body,
            excel_bytes=excel_bytes,
            filename=f"{safe_name}_data.xlsx",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Email delivery failed: {exc}") from exc

    return {"status": "sent", "to": req.to_email}
