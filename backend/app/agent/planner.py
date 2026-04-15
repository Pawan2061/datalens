from __future__ import annotations
from app.llm.base import LLMService
from app.schemas.insight import QueryPlan

class Planner:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def create_plan(self, question: str, schema_context: str) -> QueryPlan:
        return await self.llm.decompose_question(question, schema_context)
