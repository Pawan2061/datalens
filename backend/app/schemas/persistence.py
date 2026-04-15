from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

import uuid
from datetime import datetime, timezone


class UserDoc(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    email: str
    name: str
    avatar_url: str = ""
    role: str = "user"  # "admin", "manager", or "user"
    status: str = "pending"  # "pending", "active", "suspended", "expired"

    # Quota limits (set by admin)
    max_questions_per_day: int = 0  # 0 = unlimited (admin sets this)
    max_tokens_per_day: int = 0
    max_cost_usd_per_month: float = 0.0
    expiry_date: str = ""  # ISO date, empty = no expiry

    # Usage tracking
    total_questions: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    today_questions: int = 0
    today_tokens: int = 0
    today_cost_usd: float = 0.0
    month_cost_usd: float = 0.0
    usage_reset_date: str = ""  # date when today_* was last reset
    month_reset_date: str = ""

    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_login_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LoginRequest(BaseModel):
    name: str
    email: str


class GoogleLoginRequest(BaseModel):
    credential: str  # Google ID token


class GitHubLoginRequest(BaseModel):
    code: str  # GitHub OAuth authorization code


class LoginResponse(BaseModel):
    user: UserDoc
    token: str


class AdminUserUpdate(BaseModel):
    status: str | None = None  # "active", "suspended"
    role: str | None = None  # "admin", "manager", "user"
    max_questions_per_day: int | None = None
    max_tokens_per_day: int | None = None
    max_cost_usd_per_month: float | None = None
    expiry_date: str | None = None


class UsageRecord(BaseModel):
    user_id: str
    questions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    model_name: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class QuotaCheckResult(BaseModel):
    allowed: bool
    reason: str = ""
    remaining_questions: int = -1  # -1 = unlimited
    remaining_tokens: int = -1
    remaining_cost_usd: float = -1.0


class ApiToolParam(BaseModel):
    """Describes one input parameter the LLM must supply when calling the API."""
    name: str
    type: str = "string"  # string, integer, date
    required: bool = True
    description: str = ""
    default_value: str = ""  # Optional default; if set, LLM can omit


class ApiToolConfig(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str  # Human-readable name shown to manager, e.g. "SKU Stock Info"
    tool_name: str = ""  # LLM tool name (snake_case, auto-generated if empty)
    description: str = ""  # What the API does — the LLM reads this to decide when to call it
    endpoint_url: str  # Base URL (without reqCode)
    req_code: str = ""  # reqCode parameter value, e.g. "getSKUWiseStockInfo"
    method: str = "POST"  # GET or POST
    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}
    body_template: str = ""  # JSON template for POST body
    auth_config: dict[str, str] = {}  # {"apikey": "...", "token": "..."} — server-side only
    input_parameters: list[ApiToolParam] = []  # What the LLM must provide
    response_path: str = ""  # dot-notation path to extract data array (e.g. "PIECE_DETAILS")
    response_fields: list[str] = []  # Expected field names in response items
    enabled: bool = True
    test_status: str = "untested"  # "untested", "success", "failed"
    timeout_seconds: int = 30
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_by: str = ""


class WorkspaceMember(BaseModel):
    email: str
    added_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    added_by: str = ""  # user_id of who added them


class WorkspaceDoc(BaseModel):
    id: str = Field(default_factory=lambda: f"ws-{uuid.uuid4().hex[:8]}")
    owner_id: str
    name: str
    description: str = ""
    icon: str = "bar-chart-3"
    connection_ids: list[str] = []
    connections: list[dict] = []
    members: list[dict] = []  # list of WorkspaceMember dicts (emails with access)
    api_tools: list[dict] = []  # list of ApiToolConfig dicts
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WorkspaceCreateRequest(BaseModel):
    name: str
    description: str = ""
    icon: str = "bar-chart-3"
    connections: list[dict] = []
    connection_ids: list[str] = []


class WorkspaceUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    connections: Optional[list[dict]] = None
    connection_ids: Optional[list[str]] = None


class SessionDoc(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_id: str
    user_id: str
    title: str = "New Chat"
    messages: list[dict] = []
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionUpsertRequest(BaseModel):
    workspace_id: str
    title: str = "New Chat"
    messages: list[dict] = []


class SessionSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class CanvasStateDoc(BaseModel):
    id: str  # same as workspace_id
    workspace_id: str
    blocks: list[dict] = []
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CanvasSaveRequest(BaseModel):
    blocks: list[dict] = []


class AddMemberRequest(BaseModel):
    email: str


class AnalyticsEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_id: str = ""
    user_id: str = ""
    user_email: str = ""
    event_type: str = "query"  # "query", "login", "workspace_access"
    query_text: str = ""
    connection_id: str = ""
    analysis_mode: str = ""
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    model_name: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
