from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class ColumnProfile(BaseModel):
    name: str
    type: str
    distinct_count: int = 0
    null_pct: float = 0.0
    # For categorical columns
    top_values: list[str] = []  # e.g. ["Ready to Post (42%)", "Error (18%)"]
    # For numeric columns
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    avg_val: Optional[float] = None


class TableProfile(BaseModel):
    name: str
    row_count: int = 0
    columns: list[ColumnProfile] = []
    sample_rows: list[dict] = []  # TOP 3 sample records
    business_summary: str = ""  # LLM-generated description
    analysis_angles: list[str] = []  # Suggested analysis topics
    query_guidance: list[str] = []  # Data nuances: array columns, nested fields, etc.


class DirectionalQuestion(BaseModel):
    """A suggested question with a full narrative approach for the agent."""
    title: str = ""  # Short title like "Error Rate Analysis"
    question: str  # User-facing question
    narrative: str = ""  # Rich narrative paragraph: how to approach, data caveats woven in
    query_template: str = ""  # Concrete SQL/DAX query the agent can copy and adapt
    tables: list[str] = []  # Which tables to query
    key_columns: list[str] = []  # Which columns to use


class DataProfile(BaseModel):
    """Structured profile data for a database connection."""
    executive_summary: str = ""  # LLM narrative overview of the data landscape
    data_architecture: str = ""  # How tables relate, key join paths, shared dimensions
    tables: list[TableProfile] = []
    cross_table_insights: list[str] = []  # Legacy: shared columns, join hints
    suggested_questions: list[str] = []  # Simple question strings for UI
    directional_plan: list[DirectionalQuestion] = []  # Intelligence playbook


class DataProfileDoc(BaseModel):
    """Cosmos DB document for workspace intelligence profile."""
    id: str = Field(default_factory=lambda: f"profile-{uuid.uuid4().hex[:8]}")
    workspace_id: str  # Partition key
    connection_id: str
    connection_name: str = ""
    connector_type: str = ""
    status: str = "generating"  # "generating", "ready", "failed"
    profile_text: str = ""  # Rich markdown for LLM prompt injection
    raw_profile: dict = {}  # DataProfile.model_dump()
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    generation_duration_ms: float = 0.0
    error_message: str = ""


class ProfileUpdateQuestionsRequest(BaseModel):
    connection_id: str
    directional_plan: list[DirectionalQuestion] = []
    suggested_questions: list[str] = []


class ProfileGenerateRequest(BaseModel):
    connection_id: str


class ProfileStatusResponse(BaseModel):
    status: str  # "none", "generating", "ready", "failed"
    profile_id: str = ""
    generated_at: str = ""
    connection_id: str = ""
    error_message: str = ""
