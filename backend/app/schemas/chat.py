from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.insight import InsightResult


class HistoryMessage(BaseModel):
    """A condensed message from prior conversation turns."""
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    message: str
    connection_id: str
    analysis_mode: Literal["quick", "deep"] = "quick"
    workspace_id: str = ""
    user_id: str = ""  # for quota checking (set by frontend or auth middleware)
    customer_scope: str = ""       # customer_id to filter all queries; empty = admin (no filter)
    customer_scope_name: str = ""  # human-readable name shown in "Viewing as" dropdown
    history: list[HistoryMessage] = Field(default_factory=list)


class ChatMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime
    insight_result: Optional[InsightResult] = None


class SessionInfo(BaseModel):
    id: str
    title: str
    created_at: datetime
    message_count: int
