from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class AgentEventType(str, Enum):
    thinking = "thinking"
    plan = "plan"
    sub_query_start = "sub_query_start"
    sub_query_result = "sub_query_result"
    api_call_start = "api_call_start"
    api_call_result = "api_call_result"
    consolidating = "consolidating"
    narrative_chunk = "narrative_chunk"
    chart_selected = "chart_selected"
    final_result = "final_result"
    clarification = "clarification"
    error = "error"


class AgentEvent(BaseModel):
    event_type: AgentEventType
    data: dict
