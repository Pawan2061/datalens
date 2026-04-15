from __future__ import annotations

from typing import Protocol

from app.schemas.insight import InsightSummary, QueryPlan, SubQueryResult


class LLMService(Protocol):
    """Abstract interface for LLM-backed analysis services."""

    async def decompose_question(
        self, question: str, schema_context: str
    ) -> QueryPlan: ...

    async def consolidate_results(
        self, question: str, sub_results: list[SubQueryResult]
    ) -> InsightSummary: ...
