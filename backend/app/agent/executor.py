from __future__ import annotations
import time
from sqlalchemy.ext.asyncio import AsyncEngine
from app.db.query_runner import QueryRunner
from app.schemas.insight import SubQuery, SubQueryResult

class Executor:
    def __init__(self, engine: AsyncEngine):
        self.engine = engine
        self.runner = QueryRunner()

    async def execute_query(self, sub_query: SubQuery) -> SubQueryResult:
        """Execute a single sub-query and return structured result."""
        result = await self.runner.execute(self.engine, sub_query.sql)
        return SubQueryResult(
            index=sub_query.index,
            description=sub_query.description,
            sql=sub_query.sql,
            data=result["data"],
            columns=result["columns"],
            row_count=result["row_count"],
            duration_ms=result["duration_ms"],
            error=result["error"],
        )
