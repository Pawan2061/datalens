from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.auth.user_doc_cache import get_cached_user_doc, set_cached_user_doc
from app.agent.chart_recommender import recommend_charts
from app.agent.graph import run_agent
from app.agent.models import AgentEvent, AgentEventType
from app.config import settings
from app.llm.mock_llm import MockLLMService
from app.schemas.chat import ChatRequest
from app.schemas.insight import (
    ExecutionMetadata,
    InsightResult,
    SubQueryResult,
    TableData,
)

router = APIRouter()

# In-memory event queues per session
_event_queues: dict[str, asyncio.Queue] = {}
_results: dict[str, dict] = {}
_STREAM_QUEUE_WAIT_SECONDS = 10.0


def _serialize_event(event: AgentEvent) -> dict:
    """Convert AgentEvent to JSON-serializable dict."""
    return {"event_type": event.event_type.value, "data": event.data}


@router.post("/api/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or uuid.uuid4().hex[:16]
    queue = _event_queues.get(session_id)
    if queue is None:
        queue = asyncio.Queue()
        _event_queues[session_id] = queue

    await queue.put(
        AgentEvent(
            event_type=AgentEventType.thinking,
            data={"step": "request", "content": "Preparing analysis..."},
        )
    )

    # ── Guardrail Layer 1: Rule-based input filter ────────────────
    from app.guardrails.input_filter import check_input, Verdict
    layer1 = check_input(request.message)
    if layer1.verdict == Verdict.BLOCK:
        await queue.put(None)
        _event_queues.pop(session_id, None)
        raise HTTPException(
            status_code=400,
            detail=f"Request blocked: {layer1.reason}",
        )

    # ── L2 classifier + quota check run in parallel ───────────────
    # Both are I/O-bound and independent — running them concurrently
    # cuts ~600-1700 ms from the synchronous baseline.

    async def _run_layer2():
        """Run the LLM security classifier (Layer 2). Returns GuardrailResult."""
        if layer1.verdict == Verdict.FLAG:
            # Already flagged by L1 — skip the redundant LLM call
            return layer1
        try:
            from app.guardrails.llm_classifier import classify_input
            return await classify_input(request.message)
        except Exception:
            # Classifier failure → fail open (never block a legitimate user)
            return layer1

    async def _fetch_user_doc() -> "dict | None":
        """Fetch user document from DB for quota check. Returns None on miss/error."""
        if not request.user_id:
            return None
        return await _load_user_doc(request.user_id)

    layer2, user_doc = await asyncio.gather(_run_layer2(), _fetch_user_doc())

    # ── Enforce L2 verdict ────────────────────────────────────────
    if layer2.verdict == Verdict.BLOCK:
        await queue.put(None)
        _event_queues.pop(session_id, None)
        raise HTTPException(
            status_code=400,
            detail=f"Request blocked: {layer2.reason}",
        )

    # ── Enforce quota (user doc was fetched in parallel above) ────
    if user_doc:
        try:
            from app.auth.quota import check_quota
            quota = await check_quota(user_doc)
            if not quota.allowed:
                await queue.put(None)
                _event_queues.pop(session_id, None)
                raise HTTPException(status_code=429, detail=quota.reason)
        except HTTPException:
            raise
        except Exception:
            pass  # Don't block chat if quota check fails

    # Merge flag status from whichever layer fired
    if layer2.verdict == Verdict.FLAG:
        layer1 = layer2

    # Log flagged requests for audit
    if layer1.verdict == Verdict.FLAG:
        import logging
        logging.getLogger("guardrails.audit").warning(
            "FLAGGED request from user=%s: reason=%s | message=%s",
            request.user_id, layer1.reason, request.message[:200],
        )

    # Build history dicts for the agent
    history = [h.model_dump() for h in request.history] if request.history else []

    if settings.llm_provider == "mock":
        asyncio.create_task(
            _run_mock_pipeline(session_id, request.message, queue)
        )
    else:
        asyncio.create_task(
            _run_langgraph_pipeline(
                session_id=session_id,
                question=request.message,
                connection_id=request.connection_id,
                workspace_id=request.workspace_id,
                analysis_mode=request.analysis_mode,
                queue=queue,
                history=history,
                user_id=request.user_id,
                customer_scope=request.customer_scope,
                customer_scope_name=request.customer_scope_name,
            )
        )

    return {"session_id": session_id, "status": "processing"}


# ── LangGraph pipeline ──────────────────────────────────────────────

async def _run_langgraph_pipeline(
    session_id: str,
    question: str,
    connection_id: str,
    workspace_id: str,
    analysis_mode: str,
    queue: asyncio.Queue,
    history: list[dict] | None = None,
    user_id: str = "",
    customer_scope: str = "",
    customer_scope_name: str = "",
) -> None:
    """Run the LangGraph ReAct agent, pushing events to the SSE queue."""
    try:
        await run_agent(
            question=question,
            connection_id=connection_id,
            workspace_id=workspace_id,
            analysis_mode=analysis_mode,
            queue=queue,
            history=history,
            user_id=user_id,
            customer_scope=customer_scope,
            customer_scope_name=customer_scope_name,
        )

        # Record analytics event
        _record_analytics(workspace_id, user_id, question, connection_id, analysis_mode)

    except Exception as e:
        raw = str(e)
        friendly = (
            "Something went wrong while analyzing your question. "
            "Please try rephrasing or ask a simpler question."
        )
        await queue.put(
            AgentEvent(
                event_type=AgentEventType.error,
                data={"message": friendly, "detail": raw},
            )
        )
        await queue.put(None)


def _record_analytics(
    workspace_id: str, user_id: str, question: str,
    connection_id: str, analysis_mode: str,
):
    """Fire-and-forget analytics event recording."""
    try:
        from app.db.insight_db import insight_db
        if not insight_db.is_ready:
            return
        # Look up user email
        user_email = ""
        if user_id:
            cached_user = get_cached_user_doc(user_id)
            if cached_user:
                user_email = cached_user.get("email", "")
            else:
                users = insight_db.container("users")
                q = "SELECT c.email FROM c WHERE c.id = @id"
                p = [{"name": "@id", "value": user_id}]
                res = list(users.query_items(query=q, parameters=p, enable_cross_partition_query=True))
                if res:
                    user_email = res[0].get("email", "")

        from app.schemas.persistence import AnalyticsEvent
        event = AnalyticsEvent(
            workspace_id=workspace_id,
            user_id=user_id,
            user_email=user_email,
            event_type="query",
            query_text=question[:500],  # truncate long questions
            connection_id=connection_id,
            analysis_mode=analysis_mode,
        )
        container = insight_db.container("analytics_events")
        container.create_item(event.model_dump())
    except Exception:
        pass  # Never fail chat for analytics


# ── Mock pipeline (for development without API key) ──────────────────

async def _run_mock_pipeline(
    session_id: str, question: str, queue: asyncio.Queue
) -> None:
    """Run the mock agent pipeline (no real LLM calls)."""
    start_time = time.perf_counter()
    llm = MockLLMService()

    try:
        await queue.put(
            AgentEvent(
                event_type=AgentEventType.thinking,
                data={"step": "schema_inspection", "content": "Inspecting database schema..."},
            )
        )
        await asyncio.sleep(0.3)

        await queue.put(
            AgentEvent(
                event_type=AgentEventType.thinking,
                data={"step": "planning", "content": "Breaking down your question into sub-queries..."},
            )
        )

        schema_context = (
            "Table: sales | Columns: id (integer, PK), product (varchar), "
            "category (varchar), amount (numeric), sale_date (date), region (varchar)\n"
            "Table: customers | Columns: id (integer, PK), name (varchar), "
            "segment (varchar), signup_date (date), region (varchar)"
        )

        plan = await llm.decompose_question(question, schema_context)
        sub_query_dicts = [sq.model_dump() for sq in plan.sub_queries]
        plan_data: dict = {"sub_queries": sub_query_dicts}
        if hasattr(plan, "reasoning") and plan.reasoning:
            plan_data["reasoning"] = plan.reasoning

        await queue.put(AgentEvent(event_type=AgentEventType.plan, data=plan_data))

        all_results: list[SubQueryResult] = []
        mock_data_sets = _get_mock_data_for_question(question)

        for i, sq in enumerate(plan.sub_queries):
            sq_dict = sq.model_dump()
            sq_index = sq_dict.get("index", i)
            sq_description = sq_dict.get("description") or sq_dict.get("title", "")
            sq_sql = sq_dict.get("sql", "")

            await queue.put(
                AgentEvent(
                    event_type=AgentEventType.sub_query_start,
                    data={"index": sq_index, "description": sq_description, "sql": sq_sql},
                )
            )
            await asyncio.sleep(0.5)

            data = mock_data_sets[i] if i < len(mock_data_sets) else []
            columns = list(data[0].keys()) if data else []

            result = SubQueryResult(
                index=sq_index if isinstance(sq_index, int) else i,
                description=sq_description,
                sql=sq_sql,
                data=data,
                columns=columns,
                row_count=len(data),
                duration_ms=round(120 + i * 45, 2),
                error=None,
            )
            all_results.append(result)

            await queue.put(
                AgentEvent(
                    event_type=AgentEventType.sub_query_result,
                    data={
                        "index": result.index,
                        "row_count": result.row_count,
                        "duration_ms": result.duration_ms,
                        "preview": result.data[:5],
                        "error": None,
                    },
                )
            )

        await queue.put(
            AgentEvent(
                event_type=AgentEventType.consolidating,
                data={"content": f"Analyzing {len(all_results)} result sets..."},
            )
        )

        summary = await llm.consolidate_results(question, all_results)

        charts = recommend_charts(all_results)
        for chart in charts:
            await queue.put(
                AgentEvent(
                    event_type=AgentEventType.chart_selected,
                    data={
                        "chart_type": chart.chart_type.value,
                        "title": chart.title,
                        "reasoning": chart.reasoning,
                    },
                )
            )

        tables = [
            TableData(title=r.description, columns=r.columns, data=r.data)
            for r in all_results
            if r.data and not r.error
        ]

        total_duration = (time.perf_counter() - start_time) * 1000
        insight_result = InsightResult(
            summary=summary,
            charts=charts,
            tables=tables,
            execution_metadata=ExecutionMetadata(
                total_duration_ms=round(total_duration, 2),
                sub_query_count=len(all_results),
                total_rows=sum(r.row_count for r in all_results),
            ),
        )

        await queue.put(
            AgentEvent(
                event_type=AgentEventType.final_result,
                data=insight_result.model_dump(),
            )
        )
        _results[session_id] = insight_result.model_dump()

    except Exception as e:
        await queue.put(
            AgentEvent(event_type=AgentEventType.error, data={"message": str(e)})
        )

    await queue.put(None)


# ── Mock data ────────────────────────────────────────────────────────

def _get_mock_data_for_question(question: str) -> list[list[dict]]:
    """Return mock result data sets based on question keywords."""
    q = question.lower()

    if any(kw in q for kw in ["revenue", "sales"]):
        return [
            [
                {"category": "Electronics", "revenue": 2400000},
                {"category": "Clothing", "revenue": 1800000},
                {"category": "Home & Garden", "revenue": 1200000},
                {"category": "Sports", "revenue": 950000},
                {"category": "Books", "revenue": 650000},
            ],
            [
                {"month": "2024-01", "revenue": 580000},
                {"month": "2024-02", "revenue": 620000},
                {"month": "2024-03", "revenue": 710000},
                {"month": "2024-04", "revenue": 690000},
                {"month": "2024-05", "revenue": 780000},
                {"month": "2024-06", "revenue": 850000},
                {"month": "2024-07", "revenue": 920000},
                {"month": "2024-08", "revenue": 880000},
                {"month": "2024-09", "revenue": 950000},
                {"month": "2024-10", "revenue": 1020000},
                {"month": "2024-11", "revenue": 1100000},
                {"month": "2024-12", "revenue": 1200000},
            ],
        ]
    elif any(kw in q for kw in ["customer", "user"]):
        return [
            [
                {"segment": "Enterprise", "count": 450, "avg_value": 12000},
                {"segment": "SMB", "count": 1200, "avg_value": 3500},
                {"segment": "Startup", "count": 800, "avg_value": 1800},
                {"segment": "Individual", "count": 2500, "avg_value": 250},
            ],
            [
                {"month": "2024-01", "new_customers": 120},
                {"month": "2024-02", "new_customers": 135},
                {"month": "2024-03", "new_customers": 148},
                {"month": "2024-04", "new_customers": 162},
                {"month": "2024-05", "new_customers": 178},
                {"month": "2024-06", "new_customers": 195},
                {"month": "2024-07", "new_customers": 210},
                {"month": "2024-08", "new_customers": 225},
                {"month": "2024-09", "new_customers": 248},
                {"month": "2024-10", "new_customers": 267},
                {"month": "2024-11", "new_customers": 289},
                {"month": "2024-12", "new_customers": 310},
            ],
        ]
    elif any(kw in q for kw in ["trend", "growth", "over time"]):
        return [
            [
                {"quarter": "Q1 2023", "revenue": 2100000, "orders": 4200},
                {"quarter": "Q2 2023", "revenue": 2350000, "orders": 4700},
                {"quarter": "Q3 2023", "revenue": 2600000, "orders": 5100},
                {"quarter": "Q4 2023", "revenue": 2900000, "orders": 5800},
                {"quarter": "Q1 2024", "revenue": 3100000, "orders": 6200},
                {"quarter": "Q2 2024", "revenue": 3450000, "orders": 6900},
                {"quarter": "Q3 2024", "revenue": 3800000, "orders": 7600},
                {"quarter": "Q4 2024", "revenue": 4200000, "orders": 8400},
            ],
            [
                {"period": "Q1 2024 vs Q1 2023", "revenue_growth": 47.6, "order_growth": 47.6},
                {"period": "Q2 2024 vs Q2 2023", "revenue_growth": 46.8, "order_growth": 46.8},
                {"period": "Q3 2024 vs Q3 2023", "revenue_growth": 46.2, "order_growth": 49.0},
                {"period": "Q4 2024 vs Q4 2023", "revenue_growth": 44.8, "order_growth": 44.8},
            ],
        ]
    else:
        return [
            [
                {"metric": "Total Revenue", "value": 7000000},
                {"metric": "Total Orders", "value": 14500},
                {"metric": "Avg Order Value", "value": 483},
            ],
        ]


# ── SSE streaming endpoint ──────────────────────────────────────────

@router.get("/api/chat/stream/{session_id}")
async def chat_stream(session_id: str):
    """SSE endpoint -- streams agent events for a session."""
    queue: asyncio.Queue | None = None
    deadline = time.monotonic() + _STREAM_QUEUE_WAIT_SECONDS
    while time.monotonic() < deadline:
        queue = _event_queues.get(session_id)
        if queue is not None:
            break
        await asyncio.sleep(0.1)

    if queue is None:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None:
                yield {"event": "done", "data": json.dumps({"status": "complete"})}
                break

            serialized = _serialize_event(event)
            yield {
                "event": serialized["event_type"],
                "data": json.dumps(serialized["data"], default=str),
            }

        _event_queues.pop(session_id, None)

    return EventSourceResponse(event_generator())


async def _load_user_doc(user_id: str) -> dict | None:
    cached = get_cached_user_doc(user_id)
    if cached is not None:
        return cached

    try:
        from app.db.insight_db import insight_db
        if not insight_db.is_ready:
            return None
        users = insight_db.container("users")
        query = "SELECT * FROM c WHERE c.id = @id"
        params = [{"name": "@id", "value": user_id}]
        results = await asyncio.to_thread(
            lambda: list(
                users.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )
        )
        if not results:
            return None
        set_cached_user_doc(user_id, results[0])
        return results[0]
    except Exception:
        return None
