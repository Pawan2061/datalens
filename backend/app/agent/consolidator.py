from __future__ import annotations
from app.llm.base import LLMService
from app.schemas.insight import InsightSummary, SubQueryResult

class Consolidator:
    def __init__(self, llm: LLMService):
        self.llm = llm

    async def consolidate(self, question: str, results: list[SubQueryResult]) -> InsightSummary:
        return await self.llm.consolidate_results(question, results)
