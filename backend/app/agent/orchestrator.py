from __future__ import annotations
import asyncio
import time
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.models import AgentEvent, AgentEventType
from app.agent.planner import Planner
from app.agent.executor import Executor
from app.agent.consolidator import Consolidator
from app.agent.chart_recommender import recommend_charts
from app.llm.base import LLMService
from app.schemas.insight import InsightResult, ExecutionMetadata, TableData

class Orchestrator:
    def __init__(self, llm: LLMService, engine: AsyncEngine):
        self.planner = Planner(llm)
        self.executor = Executor(engine)
        self.consolidator = Consolidator(llm)

    async def process(self, question: str, schema_context: str) -> AsyncGenerator[AgentEvent, None]:
        """Process a user question through the full agent pipeline, yielding events."""
        start_time = time.perf_counter()

        # Step 1: Thinking - inspecting schema
        yield AgentEvent(
            event_type=AgentEventType.THINKING,
            data={"step": "schema_inspection", "content": "Inspecting database schema..."}
        )

        # Step 2: Planning - decompose question
        yield AgentEvent(
            event_type=AgentEventType.THINKING,
            data={"step": "planning", "content": "Breaking down your question into sub-queries..."}
        )

        try:
            plan = await self.planner.create_plan(question, schema_context)
        except Exception as e:
            yield AgentEvent(
                event_type=AgentEventType.ERROR,
                data={"message": f"Failed to create query plan: {str(e)}"}
            )
            return

        yield AgentEvent(
            event_type=AgentEventType.PLAN,
            data={
                "reasoning": plan.reasoning,
                "sub_queries": [sq.model_dump() for sq in plan.sub_queries]
            }
        )

        # Step 3: Execute sub-queries
        all_results = []
        for sub_query in plan.sub_queries:
            yield AgentEvent(
                event_type=AgentEventType.SUB_QUERY_START,
                data={
                    "index": sub_query.index,
                    "description": sub_query.description,
                    "sql": sub_query.sql,
                }
            )

            result = await self.executor.execute_query(sub_query)
            all_results.append(result)

            yield AgentEvent(
                event_type=AgentEventType.SUB_QUERY_RESULT,
                data={
                    "index": result.index,
                    "row_count": result.row_count,
                    "duration_ms": result.duration_ms,
                    "preview": result.data[:5],  # First 5 rows as preview
                    "error": result.error,
                }
            )

        # Step 4: Consolidate results
        yield AgentEvent(
            event_type=AgentEventType.CONSOLIDATING,
            data={"content": f"Analyzing {len(all_results)} result sets..."}
        )

        try:
            summary = await self.consolidator.consolidate(question, all_results)
        except Exception as e:
            yield AgentEvent(
                event_type=AgentEventType.ERROR,
                data={"message": f"Failed to consolidate results: {str(e)}"}
            )
            return

        # Step 5: Recommend charts
        charts = recommend_charts(all_results)

        for chart in charts:
            yield AgentEvent(
                event_type=AgentEventType.CHART_SELECTED,
                data={"chart_type": chart.chart_type, "title": chart.title, "reasoning": chart.reasoning}
            )

        # Step 6: Build tables
        tables = []
        for r in all_results:
            if r.data and not r.error:
                tables.append(TableData(
                    title=r.description,
                    columns=r.columns,
                    data=r.data,
                ))

        # Step 7: Final result
        total_duration = (time.perf_counter() - start_time) * 1000
        execution_metadata = ExecutionMetadata(
            total_duration_ms=round(total_duration, 2),
            sub_query_count=len(all_results),
            total_rows=sum(r.row_count for r in all_results),
        )

        insight_result = InsightResult(
            summary=summary,
            charts=charts,
            tables=tables,
            execution_metadata=execution_metadata,
        )

        yield AgentEvent(
            event_type=AgentEventType.FINAL_RESULT,
            data=insight_result.model_dump(),
        )
