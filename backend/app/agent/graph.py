from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agent.models import AgentEvent, AgentEventType
from app.agent.prompts import build_system_prompt
from app.agent.schema_cache import schema_cache
from app.agent.api_tool_cache import (
    get_cached_workspace_api_tools,
    set_cached_workspace_api_tools,
)
from app.agent.tools import (
    ask_clarification,
    execute_sql,
    refresh_schema,
)
from app.agent.tools.api_tool_factory import build_workspace_api_tools, describe_api_tools_for_prompt
from app.llm.openai_llm import get_planner_llm, get_synthesis_llm


ALL_TOOLS = [
    refresh_schema,
    ask_clarification,
    execute_sql,
]

# ── Streaming synthesis ───────────────────────────────────────────────
# Separator between narrative and metadata JSON in the LLM output.
_STREAM_SEP = "===METADATA==="

_STREAMING_SYNTHESIS_PROMPT = """\
You are a senior data analyst. Turn SQL query results into executive insights.

OUTPUT — two parts:

PART 1 — NARRATIVE:
Write a markdown narrative (2-4 paragraphs, or ## sections for multi-part questions).
Rules:
- Open with the single most important takeaway in **bold**.
- Use exact numbers from the data: percentages, totals, averages.
- Compare values: "Category A is **2.3× larger** than Category B."
- Highlight surprises or anomalies.
- End with a brief "so what" — why the reader should care, what action to consider.
- For multi-part questions (when sub_questions is provided): use ## headers per sub-question,
  then a final ## Putting It Together section that ties findings together.

Then output this separator on its own line:
===METADATA===

PART 2 — JSON (after separator, no markdown fences):
{
  "title": "Concise punchy title (e.g. 'Revenue Surged 34% — Electronics Leads')",
  "key_findings": [
    {"headline": "Short punchy insight (6-10 words)", "detail": "One sentence context", "significance": "high|medium|low"}
  ],
  "follow_up_questions": ["Specific drill-down question?"]
}

Rules: 3-5 key findings, 2-4 follow-up questions. Every number must come from the data.
Output ONLY the narrative, then the separator, then the JSON. No preamble.
"""


async def _stream_synthesis(
    question: str,
    sub_results: list[dict],
    queue: asyncio.Queue | None,
    plan: dict | None = None,
) -> dict | None:
    """Stream synthesis narrative tokens as SSE events, return full synthesis dict.

    Tokens before ===METADATA=== are emitted as narrative_chunk events so the
    frontend can display the narrative word-by-word while the LLM generates it.
    After the separator, the JSON metadata is collected silently.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Only include rows with data
    clean_results = []
    for r in sub_results:
        if r.get("error"):
            continue
        clean_results.append({
            "description": r.get("description", ""),
            "columns": r.get("columns", []),
            "data": r.get("data", [])[:50],   # cap rows to avoid huge prompts
            "row_count": r.get("row_count", 0),
        })

    if not clean_results:
        return None

    # Add sub_questions for sectioned narratives (multi-part questions)
    results_payload: dict = {"results": clean_results}
    if plan and plan.get("sub_questions"):
        results_payload["sub_questions"] = [
            sq["question"] for sq in plan["sub_questions"]
        ]

    results_json = json.dumps(results_payload, default=str)

    await _emit(queue, AgentEventType.consolidating, {
        "content": "Synthesizing insights...",
    })

    try:
        llm = get_synthesis_llm()
        messages = [
            SystemMessage(content=_STREAMING_SYNTHESIS_PROMPT),
            HumanMessage(content=f"User question: {question}\n\nQuery results:\n{results_json}"),
        ]

        full_text = ""
        narrative_done = False

        async for chunk in llm.astream(messages):
            token = chunk.content
            if not token:
                continue
            full_text += token

            if not narrative_done:
                if _STREAM_SEP in full_text:
                    # Separator found — stop emitting tokens
                    narrative_done = True
                else:
                    await _emit(queue, AgentEventType.narrative_chunk, {"token": token})

        # Split on separator
        if _STREAM_SEP in full_text:
            parts = full_text.split(_STREAM_SEP, 1)
            narrative = parts[0].strip()
            metadata_str = parts[1].strip() if len(parts) > 1 else "{}"
        else:
            narrative = full_text.strip()
            metadata_str = "{}"

        # Strip markdown fences if present
        if metadata_str.startswith("```"):
            lines = metadata_str.split("\n")
            metadata_str = "\n".join(l for l in lines if not l.startswith("```")).strip()

        try:
            metadata = json.loads(metadata_str)
        except json.JSONDecodeError:
            metadata = {}

        return {
            "title": metadata.get("title", ""),
            "narrative": narrative,
            "key_findings": metadata.get("key_findings", []),
            "follow_up_questions": metadata.get("follow_up_questions", []),
        }

    except Exception as exc:
        logger.warning("Streaming synthesis failed (will use heuristic fallback): %s", exc)
        return None


async def run_agent(
    question: str,
    connection_id: str,
    workspace_id: str = "",
    analysis_mode: str = "quick",
    selected_tables: list[str] | None = None,
    queue: asyncio.Queue | None = None,
    history: list[dict] | None = None,
    user_id: str = "",
    customer_scope: str = "",
) -> AsyncGenerator[AgentEvent, None]:
    """Run the LangGraph ReAct agent and yield SSE events.

    If a queue is provided, events are also pushed to the queue for the
    SSE streaming endpoint.
    """
    start_time = time.perf_counter()

    # ── Quick response check (saves LLM call entirely) ───────────
    from app.agent.quick_responses import detect_quick_response, response_cache

    quick = detect_quick_response(question)
    if quick:
        total_duration = (time.perf_counter() - start_time) * 1000
        final = _build_conversational_result(quick, total_duration)
        await _emit(queue, AgentEventType.final_result, final)
        await _emit_done(queue)
        return

    # ── Response cache check ─────────────────────────────────────
    cached = response_cache.get(question, connection_id)
    if cached:
        await _emit(queue, AgentEventType.thinking, {
            "step": "cache_hit",
            "content": "Found cached result for similar question...",
        })
        # Update duration to reflect cache hit
        cached_copy = dict(cached)
        if "execution_metadata" in cached_copy:
            cached_copy["execution_metadata"] = dict(cached_copy["execution_metadata"])
            cached_copy["execution_metadata"]["total_duration_ms"] = round(
                (time.perf_counter() - start_time) * 1000, 2
            )
            cached_copy["execution_metadata"]["cached"] = True
        await _emit(queue, AgentEventType.final_result, cached_copy)
        await _emit_done(queue)
        return

    # ── Chit-chat → cheap model (Haiku) ─────────────────────────────
    from app.agent.quick_responses import is_conversational
    if is_conversational(question):
        await _emit(queue, AgentEventType.thinking, {
            "step": "conversational",
            "content": "Processing your message...",
        })
        try:
            response_text = await _run_cheap_conversational(
                question, connection_id, workspace_id, history,
            )
            total_duration = (time.perf_counter() - start_time) * 1000
            final = _build_conversational_result(response_text, total_duration)
            response_cache.put(question, connection_id, final)
            await _emit(queue, AgentEventType.final_result, final)
            await _emit_done(queue)
            return
        except Exception:
            pass  # Fall through to full agent if cheap model fails

    # ── Emit: thinking (schema) ──────────────────────────────────────
    await _emit(queue, AgentEventType.thinking, {
        "step": "schema_cache",
        "content": "Loading database schema...",
    })

    # Determine connector type
    from app.db.connection_manager import connection_manager
    conn_type = connection_manager.get_connection_type(connection_id) or "postgresql"
    _CONNECTOR_LABELS = {
        "cosmosdb": "Azure Cosmos DB",
        "powerbi": "Power BI",
    }
    connector_label = _CONNECTOR_LABELS.get(conn_type, "PostgreSQL")

    # Load workspace profile, API tools, and schema in parallel.
    # Schema is always fetched speculatively — instant when cached (TTL: 1 hour).
    # If the workspace profile is available, schema is discarded; otherwise it's
    # already in hand, saving a sequential round-trip after the profile returns.
    profile_text = ""
    api_tool_configs: list[dict] = []
    schema_text = ""

    if workspace_id:
        from app.agent.profiler import load_profile

        async def _load_api_tools() -> list[dict]:
            cached_tools = get_cached_workspace_api_tools(workspace_id)
            if cached_tools is not None:
                return cached_tools
            try:
                from app.db.insight_db import insight_db
                if not insight_db.is_ready:
                    return []
                container = insight_db.container("workspaces")
                items = await asyncio.to_thread(
                    lambda: list(container.query_items(
                        query="SELECT c.api_tools FROM c WHERE c.id = @wid",
                        parameters=[{"name": "@wid", "value": workspace_id}],
                        partition_key=workspace_id,
                    ))
                )
                tools = items[0]["api_tools"] if items and items[0].get("api_tools") else []
                set_cached_workspace_api_tools(workspace_id, tools)
                return tools
            except Exception:
                return []  # API tools are optional — don't block analysis

        profile_doc, api_tool_configs, schema_text = await asyncio.gather(
            load_profile(workspace_id, connection_id),
            _load_api_tools(),
            schema_cache.get(connection_id),  # Speculative — free when cached
        )
        if profile_doc and profile_doc.status == "ready" and profile_doc.profile_text:
            profile_text = profile_doc.profile_text
            schema_text = ""  # Profile takes precedence — discard preloaded schema
    else:
        # No workspace context — load schema directly
        schema_text = await schema_cache.get(connection_id)

    # Build system prompt
    system_prompt = build_system_prompt(
        schema=schema_text,
        connection_id=connection_id,
        selected_tables=selected_tables,
        analysis_mode=analysis_mode,
        connector_type=connector_label,
        workspace_profile=profile_text,
    )

    # Append API tool descriptions to the prompt so the LLM knows about them
    if api_tool_configs:
        system_prompt += describe_api_tools_for_prompt(api_tool_configs)

    # ── Pre-plan complex questions with Gemini Flash (free) ─────────
    await _emit(queue, AgentEventType.thinking, {
        "step": "planning",
        "content": "Analyzing your question...",
    })

    plan_addendum = ""
    plan: dict | None = None
    try:
        from app.agent.pre_planner import pre_plan, format_plan_for_agent
        schema_for_plan = profile_text or schema_text
        plan = await pre_plan(question, schema_for_plan)
        if plan:
            plan_addendum = format_plan_for_agent(plan)
            await _emit(queue, AgentEventType.thinking, {
                "step": "planning",
                "content": f"Breaking down into {len(plan.get('sub_questions', []))} sub-questions...",
            })
    except Exception:
        pass  # Pre-planner is optional — if it fails, agent proceeds normally

    # ── Customer scope filter (injected when not admin) ─────────────
    scope_addendum = ""
    if customer_scope:
        scope_addendum = (
            f"\n\n━━ CUSTOMER SCOPE FILTER ━━\n"
            f"You are operating in CUSTOMER mode for customer_id = {customer_scope}.\n"
            f"CRITICAL: Every SQL query MUST include a WHERE clause (or equivalent filter) "
            f"that restricts results to customer_id = {customer_scope}.\n"
            f"If a table does not have a customer_id column, join it to the relevant table "
            f"that does. NEVER return data for other customers.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    # Append the execution roadmap to the system prompt
    agent_prompt = system_prompt + scope_addendum + plan_addendum

    # Create the ReAct agent graph
    # Quick mode → Haiku (tool calling). Deep mode → Sonnet (thorough).
    # Exception: complex plans get Sonnet even in quick mode (Haiku can't handle 3+ step plans)
    from app.llm.openai_llm import get_agent_llm
    plan_complexity = plan.get("complexity", "").lower() if plan else ""

    use_strong_model = (
        analysis_mode == "deep"
        or plan_complexity in ("complex", "moderate")
    )
    llm = get_planner_llm() if use_strong_model else get_agent_llm()

    # Build dynamic API tools for this workspace and merge with built-in tools
    dynamic_api_tools = build_workspace_api_tools(api_tool_configs) if api_tool_configs else []
    all_tools = ALL_TOOLS + dynamic_api_tools
    # Track dynamic tool names for result handling
    dynamic_tool_names = {t.name for t in dynamic_api_tools}

    graph = create_react_agent(
        model=llm,
        tools=all_tools,
        prompt=agent_prompt,
    )

    # Stream through the agent's execution
    sub_query_index = 0
    all_sub_results: list[dict] = []
    agent_final_text = ""  # Capture the agent's last text response
    # Token usage tracking
    total_input_tokens = 0
    total_output_tokens = 0
    model_name = ""
    # Captured tool outputs for the final result
    synthesis_output: dict | None = None       # analyze_results JSON output
    agent_chart_recs: list[dict] | None = None # recommend_charts_tool JSON output
    # Tracking maps for tool call support
    pending_descriptions: dict[str, str] = {}  # execute_sql tool_call_id -> description
    pending_sql: dict[str, str] = {}           # execute_sql tool_call_id -> SQL
    query_start_index = 0  # counter for sub_query_start events

    # Build conversation messages: history (condensed) + current question
    _role_map = {"user": "human", "assistant": "ai"}
    conversation: list[tuple[str, str]] = []
    if history:
        for h in history[-6:]:  # Keep last 6 messages for cost efficiency
            role = _role_map.get(h.get("role", ""), "human")
            conversation.append((role, h.get("content", "")))
    conversation.append(("human", question))

    try:
     async for chunk in graph.astream(
        {"messages": conversation},
        stream_mode="updates",
     ):
        # Process each node's output
        for node_name, node_output in chunk.items():
            if node_name == "tools":
                # Tool node returned results
                messages = node_output.get("messages", [])
                for msg in messages:
                    # Track token usage
                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                        um = msg.usage_metadata
                        total_input_tokens += um.get('input_tokens', 0)
                        total_output_tokens += um.get('output_tokens', 0)
                        if not model_name and hasattr(msg, 'response_metadata'):
                            model_name = msg.response_metadata.get('model', '') or msg.response_metadata.get('model_name', '')
                    tool_name = getattr(msg, "name", "")
                    content = msg.content if hasattr(msg, "content") else str(msg)

                    if tool_name == "ask_clarification":
                        # Agent wants to ask user a question
                        clarification_text = content.replace("CLARIFICATION_NEEDED: ", "")
                        await _emit(queue, AgentEventType.clarification, {
                            "question": clarification_text,
                        })
                        # Signal end — the frontend will show the question
                        await _emit_done(queue)
                        return

                    elif tool_name == "execute_sql":
                        try:
                            result_data = json.loads(content)
                        except json.JSONDecodeError:
                            result_data = {"error": content, "data": [], "columns": [], "row_count": 0, "duration_ms": 0}

                        # Look up description and SQL via tool_call_id
                        tool_call_id = getattr(msg, "tool_call_id", "")
                        desc = pending_descriptions.pop(tool_call_id, "").strip()
                        sql = pending_sql.pop(tool_call_id, "").strip()
                        if not desc:
                            desc = f"Query {sub_query_index + 1}"
                        result_data["index"] = sub_query_index
                        result_data["description"] = desc
                        result_data["sql"] = sql
                        all_sub_results.append(result_data)

                        raw_err = result_data.get("error")
                        await _emit(queue, AgentEventType.sub_query_result, {
                            "index": sub_query_index,
                            "row_count": result_data.get("row_count", 0),
                            "duration_ms": result_data.get("duration_ms", 0),
                            "preview": result_data.get("data", [])[:5],
                            "error": _friendly_error(raw_err) if raw_err else None,
                            "error_detail": raw_err,
                            "sql": sql,
                        })
                        sub_query_index += 1

                    elif tool_name == "refresh_schema":
                        await _emit(queue, AgentEventType.thinking, {
                            "step": "schema_refresh",
                            "content": "Refreshing database schema...",
                        })

                    elif tool_name in dynamic_tool_names:
                        # Dynamic API tool result
                        try:
                            api_result = json.loads(content)
                        except json.JSONDecodeError:
                            api_result = {"error": content, "data": [], "columns": [], "row_count": 0}

                        api_name = api_result.get("api_name", tool_name)
                        api_error = api_result.get("error")

                        # Treat API results like sub-query results so they flow
                        # through analyze_results and recommend_charts_tool
                        desc = f"API: {api_name}"
                        api_result["index"] = sub_query_index
                        api_result["description"] = desc
                        api_result["sql"] = f"[API Call: {api_name}]"
                        all_sub_results.append(api_result)

                        await _emit(queue, AgentEventType.api_call_result, {
                            "index": sub_query_index,
                            "api_name": api_name,
                            "row_count": api_result.get("row_count", 0),
                            "duration_ms": api_result.get("duration_ms", 0),
                            "preview": api_result.get("data", [])[:3],
                            "error": api_error,
                        })
                        sub_query_index += 1

            elif node_name == "agent":
                # Capture the agent's text response AND tool call descriptions
                messages = node_output.get("messages", [])
                for msg in messages:
                    # Track token usage
                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                        um = msg.usage_metadata
                        total_input_tokens += um.get('input_tokens', 0)
                        total_output_tokens += um.get('output_tokens', 0)
                        if not model_name and hasattr(msg, 'response_metadata'):
                            model_name = msg.response_metadata.get('model', '') or msg.response_metadata.get('model_name', '')
                    text = getattr(msg, "content", "")
                    tool_calls = getattr(msg, "tool_calls", [])

                    # Only capture non-empty text (skip tool-call-only messages)
                    if text and isinstance(text, str) and text.strip():
                        agent_final_text = text.strip()

                        # Stream agent reasoning to the user when the agent
                        # is THINKING before calling tools (not final response)
                        if tool_calls:
                            # Agent produced reasoning + is about to call tools
                            # Truncate very long thoughts for the step display
                            thought = text.strip()
                            if len(thought) > 300:
                                thought = thought[:297] + "..."
                            await _emit(queue, AgentEventType.thinking, {
                                "step": "reasoning",
                                "content": thought,
                            })

                    # Capture tool call metadata for execute_sql tracking
                    for tc in tool_calls:
                        tc_name = tc.get("name", "")
                        tc_id = tc.get("id", "")
                        if tc_name == "execute_sql":
                            tc_sql = tc.get("args", {}).get("sql", "").strip()
                            if tc_id:
                                pending_sql[tc_id] = tc_sql
                                # Generate a human-readable description from the SQL
                                desc = _describe_sql(tc_sql)
                                await _emit(queue, AgentEventType.sub_query_start, {
                                    "index": query_start_index,
                                    "description": desc or f"Query {query_start_index + 1}",
                                    "sql": tc_sql,
                                })
                                query_start_index += 1
                        elif tc_name in dynamic_tool_names:
                            await _emit(queue, AgentEventType.api_call_start, {
                                "api_name": tc_name,
                                "content": f"Calling external API: {tc_name}...",
                            })

    except Exception as agent_err:
        # Agent crashed mid-execution — log but continue with partial results
        import logging
        logger = logging.getLogger(__name__)
        logger.error("Agent execution error: %s", agent_err, exc_info=True)
        err_str = str(agent_err)[:200]

        # If we have ANY sub-results, fall through to build partial results
        if all_sub_results:
            await _emit(queue, AgentEventType.thinking, {
                "step": "recovery",
                "content": "Completing analysis with available data...",
            })
        elif agent_final_text:
            pass  # Fall through — agent wrote some text before crashing
        else:
            # Truly nothing collected — emit error with details and return
            error_hint = "Try breaking your question into simpler parts, or try again."
            if "timeout" in err_str.lower() or "timed out" in err_str.lower():
                error_hint = "The analysis took too long. Try a simpler question."
            elif "rate" in err_str.lower() or "429" in err_str:
                error_hint = "The AI service is temporarily busy. Please try again in a moment."
            elif "context" in err_str.lower() or "token" in err_str.lower():
                error_hint = "The question required too much context. Try asking a more focused question."

            await _emit(queue, AgentEventType.final_result, {
                "summary": {
                    "title": "Analysis Incomplete",
                    "narrative": (
                        f"The analysis encountered an issue and couldn't fully complete. "
                        f"{error_hint}\n\n"
                        f"Technical detail: {err_str}"
                    ),
                    "key_findings": [],
                    "follow_up_questions": [
                        "Who are my top 10 customers by revenue?",
                        "What is the monthly revenue trend for the last 12 months?",
                        "Show me customer revenue percentages",
                    ],
                },
                "charts": [],
                "tables": [],
                "execution_metadata": {
                    "total_duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
                    "sub_query_count": len(all_sub_results),
                    "total_rows": 0,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens,
                    "model_name": model_name,
                    "estimated_cost_usd": 0.0,
                },
            })
            await _emit_done(queue)
            return
        # Fall through to build partial results from whatever we collected

    # ── Streaming synthesis (runs after the agent finishes all SQL) ──
    # analyze_results is no longer an agent tool — synthesis runs here so
    # we can stream the narrative token-by-token before the final result.
    if all_sub_results and not synthesis_output:
        try:
            synthesis_output = await _stream_synthesis(
                question, all_sub_results, queue, plan=plan
            )
        except Exception:
            pass  # Synthesis failure → heuristic fallback in _build_final_result

    # ── Build final result ───────────────────────────────────────────
    total_duration = (time.perf_counter() - start_time) * 1000

    # If no queries were executed, the agent responded conversationally
    if sub_query_index == 0 and agent_final_text:
        final_result = _build_conversational_result(
            agent_final_text, total_duration,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model_name=model_name,
        )
    else:
        # Standard analysis path — use synthesis + chart outputs from agent tools
        # Safety net: if the agent skipped recommend_charts_tool but has data,
        # the heuristic fallback inside _build_final_result will generate charts.
        final_result = _build_final_result(
            all_sub_results, total_duration,
            synthesis=synthesis_output,
            agent_charts=agent_chart_recs,
            agent_narrative=agent_final_text,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            model_name=model_name,
        )

    # ── Guardrail Layer 4: Response guard ────────────────────────
    from app.guardrails.response_guard import scrub_insight_result
    final_result = scrub_insight_result(final_result)

    # Cache the result for future similar questions
    response_cache.put(question, connection_id, final_result)

    await _emit(queue, AgentEventType.final_result, final_result)

    # ── Record usage if user_id was provided ─────────────────────
    if user_id:
        try:
            from app.auth.quota import record_usage
            meta = final_result.get("execution_metadata", {})
            await record_usage(
                user_id=user_id,
                total_tokens=meta.get("total_tokens", 0),
                cost_usd=meta.get("estimated_cost_usd", 0.0),
                questions=1,
                input_tokens=meta.get("input_tokens", 0),
                output_tokens=meta.get("output_tokens", 0),
                model_name=meta.get("model_name", ""),
            )
        except Exception:
            pass  # Don't fail chat if usage recording fails

    await _emit_done(queue)


def _build_conversational_result(agent_text: str, total_duration_ms: float, input_tokens: int = 0, output_tokens: int = 0, model_name: str = "") -> dict:
    """Build an InsightResult for conversational (non-query) responses.

    Parses the agent's structured response into title, narrative,
    key_findings (rendered as topic cards), and follow_up_questions.
    """
    from app.schemas.insight import (
        ExecutionMetadata,
        InsightResult,
        InsightSummary,
        KeyFinding,
    )

    title = ""
    narrative_lines: list[str] = []
    key_findings: list[KeyFinding] = []
    follow_ups: list[str] = []

    # Determine which section we're in while scanning lines
    section = "preamble"  # preamble → narrative → insights → questions

    for line in agent_text.split("\n"):
        stripped = line.strip()

        # ── Detect TITLE: prefix ──────────────────────────────
        if stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip().strip('"').strip("'")
            continue

        # ── Detect section headers ────────────────────────────
        upper = stripped.upper().rstrip(":")
        if upper in ("INSIGHTS", "TOPICS", "WHAT I CAN HELP WITH",
                      "AVAILABLE INSIGHTS", "INSIGHT TOPICS"):
            section = "insights"
            continue
        if upper in ("QUESTIONS", "TRY ASKING", "SUGGESTED QUESTIONS",
                      "EXPLORE FURTHER", "EXAMPLE QUESTIONS"):
            section = "questions"
            continue

        # ── Route content to the right bucket ─────────────────
        if section in ("preamble", "narrative"):
            # Skip empty lines at the very start
            if section == "preamble" and not stripped:
                continue
            section = "narrative"
            narrative_lines.append(line)

        elif section == "insights":
            if not stripped or stripped == "---":
                continue
            # Expected format: - **Topic Name** | Description | significance
            # Also handle: - Topic Name | Description | significance
            # Also handle: - **Topic Name** — Description (no pipe separator)
            bullet = stripped.lstrip("-•*– ").strip()
            if not bullet:
                continue

            # Try pipe-separated format first
            if "|" in bullet:
                parts = [p.strip() for p in bullet.split("|")]
                headline = parts[0].strip("*").strip()
                detail = parts[1] if len(parts) > 1 else ""
                sig = parts[2].strip().lower() if len(parts) > 2 else "medium"
                if sig not in ("high", "medium", "low"):
                    sig = "medium"
                key_findings.append(KeyFinding(
                    headline=headline, detail=detail, significance=sig,
                ))
            elif " — " in bullet or " - " in bullet:
                # Fallback: dash-separated
                sep = " — " if " — " in bullet else " - "
                parts = bullet.split(sep, 1)
                headline = parts[0].strip("*").strip()
                detail = parts[1].strip() if len(parts) > 1 else ""
                key_findings.append(KeyFinding(
                    headline=headline, detail=detail, significance="medium",
                ))
            else:
                # Plain bullet — just a headline
                headline = bullet.strip("*").strip()
                key_findings.append(KeyFinding(
                    headline=headline, detail="", significance="medium",
                ))

        elif section == "questions":
            q = stripped.lstrip("-•*0123456789.) ").strip()
            if q.endswith("?") and len(q) > 10:
                follow_ups.append(q)

    # ── Fallback: if the agent didn't use structured format ───
    if not key_findings and not follow_ups:
        # Try to extract questions from anywhere in the text
        for line in agent_text.split("\n"):
            q = line.strip().lstrip("-•*0123456789.) ").strip()
            if q.endswith("?") and len(q) > 15:
                follow_ups.append(q)

    narrative = "\n".join(narrative_lines).strip()
    if not narrative:
        # If no narrative section found, use the full text minus parsed parts
        narrative = agent_text

    summary = InsightSummary(
        title=title or "",
        narrative=narrative,
        key_findings=key_findings[:6],
        follow_up_questions=follow_ups[:5],
    )

    metadata = ExecutionMetadata(
        total_duration_ms=round(total_duration_ms, 2),
        sub_query_count=0,
        total_rows=0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        model_name=model_name,
        estimated_cost_usd=_estimate_cost(input_tokens, output_tokens, model_name),
    )

    result = InsightResult(
        summary=summary,
        charts=[],
        tables=[],
        execution_metadata=metadata,
    )
    return result.model_dump()


def _build_final_result(
    sub_results: list[dict],
    total_duration_ms: float,
    synthesis: dict | None = None,
    agent_charts: list[dict] | None = None,
    agent_narrative: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    model_name: str = "",
) -> dict:
    """Build an InsightResult-compatible dict from collected sub-query results.

    Uses the agent's analyze_results synthesis and recommend_charts_tool output
    when available, falling back to heuristic analysis when they're missing.
    """
    from app.agent.chart_recommender import recommend_charts as heuristic_charts, _merge_compatible_charts
    from app.schemas.insight import (
        ChartRecommendation,
        ChartType,
        ExecutionMetadata,
        InsightResult,
        InsightSummary,
        KeyFinding,
        SubQueryResult,
        TableData,
    )

    # Convert raw dicts to SubQueryResult
    sub_query_results = []
    for r in sub_results:
        if r.get("error"):
            continue
        sub_query_results.append(SubQueryResult(
            index=r.get("index", 0),
            description=r.get("description", ""),
            sql=r.get("sql", ""),
            data=r.get("data", []),
            columns=r.get("columns", []),
            row_count=r.get("row_count", 0),
            duration_ms=r.get("duration_ms", 0),
        ))

    # ── Charts: prefer agent's recommend_charts_tool output ──────────
    valid_chart_types = {ct.value for ct in ChartType}
    charts: list[ChartRecommendation] = []
    if agent_charts:
        for ac in agent_charts:
            try:
                ct = ac.get("chart_type", "table")
                charts.append(ChartRecommendation(
                    chart_type=ChartType(ct) if ct in valid_chart_types else ChartType.table,
                    title=ac.get("title", ""),
                    x_axis=ac.get("x_axis"),
                    y_axis=ac.get("y_axis"),
                    color_by=ac.get("color_by"),
                    reasoning=ac.get("reasoning", ""),
                    data=ac.get("data", []),
                    config=ac.get("config"),
                ))
            except Exception:
                continue
    if not charts:
        # Fallback to heuristic chart recommender (already applies merge internally)
        charts = heuristic_charts(sub_query_results)
    else:
        # Agent charts may still need merging if the tool didn't merge them
        charts = _merge_compatible_charts(charts)

    # Build tables ONLY for results whose chart type is "table"
    charted_descriptions: set[str] = set()
    for c in charts:
        if c.chart_type.value == "table":
            continue
        if " vs " in c.title:
            for part in c.title.split(" vs "):
                charted_descriptions.add(part.strip())
        else:
            charted_descriptions.add(c.title)

    tables = [
        TableData(
            title=r.description,
            columns=r.columns,
            data=r.data,
        )
        for r in sub_query_results
        if r.data and r.description not in charted_descriptions
    ]

    total_rows = sum(r.row_count for r in sub_query_results)
    has_data = total_rows > 0

    # ── Summary: prefer agent's analyze_results synthesis ────────────
    if synthesis and has_data:
        # Use the rich synthesis from the analyze_results tool
        syn_findings = []
        for kf in synthesis.get("key_findings", []):
            syn_findings.append(KeyFinding(
                headline=kf.get("headline", ""),
                detail=kf.get("detail", ""),
                significance=kf.get("significance", "medium"),
            ))
        summary = InsightSummary(
            title=synthesis.get("title", "Analysis Results"),
            narrative=synthesis.get("narrative", ""),
            key_findings=syn_findings[:6],
            follow_up_questions=synthesis.get("follow_up_questions", [])[:5],
        )
    elif has_data:
        # Fallback: if agent wrote a narrative text (but didn't call analyze_results), use it
        if agent_narrative:
            # The agent may have emitted raw JSON (a synthesis dict) as its final text
            # instead of calling analyze_results. Try to parse it.
            _parsed_narrative = None
            try:
                _maybe_json = json.loads(agent_narrative)
                if isinstance(_maybe_json, dict) and "narrative" in _maybe_json:
                    _parsed_findings = []
                    for kf in _maybe_json.get("key_findings", []):
                        if isinstance(kf, dict):
                            _parsed_findings.append(KeyFinding(
                                headline=kf.get("headline", ""),
                                detail=kf.get("detail", ""),
                                significance=kf.get("significance", "medium"),
                            ))
                    _parsed_narrative = InsightSummary(
                        title=_maybe_json.get("title", sub_query_results[0].description if sub_query_results else "Analysis Results"),
                        narrative=_maybe_json["narrative"],
                        key_findings=_parsed_findings[:6],
                        follow_up_questions=_maybe_json.get("follow_up_questions", [])[:5],
                    )
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

            summary = _parsed_narrative or InsightSummary(
                title=sub_query_results[0].description if sub_query_results else "Analysis Results",
                narrative=agent_narrative,
                key_findings=[],
                follow_up_questions=[],
            )
        else:
            # Build data-driven findings from raw query results
            fallback_findings: list[KeyFinding] = []
            for r in sub_query_results:
                if not r.data:
                    continue
                numeric_cols = [
                    col for col in r.columns
                    if r.data and isinstance(r.data[0].get(col), (int, float))
                ]
                if numeric_cols and len(r.data) >= 2:
                    col = numeric_cols[0]
                    values = [row[col] for row in r.data if row.get(col) is not None]
                    if values:
                        top_val = max(values)
                        cat_cols = [c for c in r.columns if c != col]
                        top_row = next((row for row in r.data if row.get(col) == top_val), None)
                        label = str(top_row.get(cat_cols[0], "")) if top_row and cat_cols else ""
                        if label:
                            fallback_findings.append(KeyFinding(
                                headline=f"{label} leads with {top_val:,.2f}" if isinstance(top_val, float) else f"{label} leads with {top_val:,}",
                                detail=r.description or f"Across {r.row_count} records analyzed",
                                significance="high" if len(fallback_findings) == 0 else "medium",
                            ))
                if len(fallback_findings) >= 3:
                    break

            if not fallback_findings:
                fallback_findings = [
                    KeyFinding(
                        headline=f"Analyzed {total_rows:,} records across {len(sub_query_results)} queries",
                        detail="See the charts and tables below for detailed breakdowns",
                        significance="medium",
                    )
                ]

            summary = InsightSummary(
                title=sub_query_results[0].description if sub_query_results else "Analysis Results",
                narrative="Analysis complete — explore the visualizations below for the full picture.",
                key_findings=fallback_findings,
                follow_up_questions=[],
            )
    else:
        summary = InsightSummary(
            title="No Data Found",
            narrative=(
                "The queries executed successfully but returned no results. "
                "This may be due to date filters not matching the available data range, "
                "or the specific criteria having no matching records. "
                "Try broadening your question or asking about a different time period."
            ),
            key_findings=[
                KeyFinding(
                    headline="0 rows returned",
                    detail="All queries came back empty — try a broader question",
                    significance="low",
                )
            ],
            follow_up_questions=[],
        )

    metadata = ExecutionMetadata(
        total_duration_ms=round(total_duration_ms, 2),
        sub_query_count=len(sub_query_results),
        total_rows=sum(r.row_count for r in sub_query_results),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        model_name=model_name,
        estimated_cost_usd=_estimate_cost(input_tokens, output_tokens, model_name),
    )

    result = InsightResult(
        summary=summary,
        charts=charts,
        tables=tables,
        execution_metadata=metadata,
    )
    return result.model_dump()


async def _emit(
    queue: asyncio.Queue | None,
    event_type: AgentEventType,
    data: dict,
) -> None:
    """Push an event to the queue."""
    if queue is not None:
        await queue.put(AgentEvent(event_type=event_type, data=data))


async def _emit_done(queue: asyncio.Queue | None) -> None:
    """Signal end of stream."""
    if queue is not None:
        await queue.put(None)


# ── User-friendly error translation ─────────────────────────────────

_ERROR_PATTERNS: list[tuple[str, str]] = [
    ("bad request", "The query syntax wasn't quite right — adjusting and retrying."),
    ("one of the input values is invalid", "A column type mismatch was detected — fixing the query."),
    ("resource not found", "The requested data source wasn't found — checking available tables."),
    ("syntax error", "Query syntax issue detected — rewriting the query."),
    ("cross partition", "Query requires a cross-partition scan — simplifying the approach."),
    ("request rate is large", "The database is busy — retrying in a moment."),
    ("timeout", "The query took too long — simplifying and retrying."),
    ("request entity too large", "The query result was too large — adding filters to narrow it down."),
    ("could not determine container", "Couldn't identify which data source to query — checking the schema."),
    ("connection", "Temporary connection issue — retrying."),
    ("cosmos db error", "Database returned an error — the agent is adjusting its approach."),
]


def _friendly_error(raw_error: str) -> str:
    """Translate raw technical errors into user-friendly messages."""
    if not raw_error:
        return ""
    lower = raw_error.lower()
    for pattern, friendly in _ERROR_PATTERNS:
        if pattern in lower:
            return friendly
    # Fallback: strip technical noise but keep it short
    if len(raw_error) > 120:
        return "Encountered a data query issue — the agent is working on a fix."
    return "Query issue detected — adjusting approach."


def _describe_sql(sql: str) -> str:
    """Generate a short human-readable description from a SQL query."""
    if not sql:
        return ""
    upper = sql.upper().strip()
    # Extract table/container name
    table = ""
    for keyword in ("FROM ", "FROM\n"):
        idx = upper.find(keyword)
        if idx >= 0:
            rest = sql[idx + len(keyword):].strip()
            table = rest.split()[0].strip() if rest else ""
            break
    # Detect aggregation type
    has_avg = "AVG(" in upper
    has_count = "COUNT(" in upper
    has_sum = "SUM(" in upper
    has_min_max = "MIN(" in upper or "MAX(" in upper
    has_group = "GROUP BY" in upper
    has_top = "SELECT TOP" in upper or "LIMIT" in upper

    parts: list[str] = []
    if has_count and has_avg:
        parts.append("Counting and averaging")
    elif has_count:
        parts.append("Counting")
    elif has_avg:
        parts.append("Calculating averages")
    elif has_sum:
        parts.append("Summing")
    elif has_min_max:
        parts.append("Finding ranges")
    elif has_top:
        parts.append("Sampling")
    else:
        parts.append("Querying")

    if table:
        parts.append(f"from {table}")
    if has_group:
        parts.append("with grouping")

    return " ".join(parts)


def _estimate_cost(input_tokens: int, output_tokens: int, model_name: str) -> float:
    """Estimate USD cost based on token counts and model."""
    # Pricing per 1M tokens (approximate)
    _PRICING = {
        "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5": {"input": 0.8, "output": 4.0},
        "claude-opus-4-0": {"input": 15.0, "output": 75.0},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4.1-mini": {"input": 0.4, "output": 1.6},
        "gemini-2.0-flash": {"input": 0.0, "output": 0.0},  # FREE tier
        "gemini-2.5-flash": {"input": 0.0, "output": 0.0},  # FREE tier
        "gemini": {"input": 0.0, "output": 0.0},  # FREE tier fallback
    }
    # Find matching pricing
    pricing = None
    model_lower = model_name.lower()
    for key, p in _PRICING.items():
        if key in model_lower:
            pricing = p
            break
    if not pricing:
        # Default: assume cheap model
        pricing = {"input": 1.0, "output": 5.0}

    cost = (input_tokens * pricing["input"] / 1_000_000) + (output_tokens * pricing["output"] / 1_000_000)
    return round(cost, 6)


# ── Cheap conversational handler (Haiku) ─────────────────────────

async def _run_cheap_conversational(
    question: str,
    connection_id: str,
    workspace_id: str = "",
    history: list[dict] | None = None,
) -> str:
    """Handle conversational messages with the cheapest model (Haiku).

    Uses a minimal prompt (~500 tokens) instead of the full 3K+ token
    system prompt + ReAct agent loop. Saves ~90% on conversational turns.
    """
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.llm.openai_llm import get_worker_llm
    from app.agent.schema_cache import schema_cache

    # Build a tiny schema summary (just table names + column counts)
    schema_summary = ""
    if workspace_id:
        from app.agent.profiler import load_profile
        profile_doc = await load_profile(workspace_id, connection_id)
        if profile_doc and profile_doc.status == "ready":
            raw = profile_doc.raw_profile or {}
            tables = raw.get("tables", [])
            if tables:
                parts = []
                for t in tables[:15]:
                    name = t.get("name", "")
                    cols = t.get("columns", [])
                    col_names = [c.get("name", "") for c in cols[:8]]
                    parts.append(f"- {name} ({len(cols)} cols: {', '.join(col_names)}{'...' if len(cols) > 8 else ''})")
                schema_summary = "Available tables:\n" + "\n".join(parts)

    if not schema_summary:
        try:
            raw_schema = await schema_cache.get(connection_id)
            if raw_schema:
                # Just take the first 500 chars as a hint
                schema_summary = raw_schema[:500]
        except Exception:
            schema_summary = "(Database connected)"

    prompt = f"""\
You are DataLens, a friendly data analyst assistant. The user is chatting casually.
Respond naturally in 1-3 sentences. Be warm, helpful, and concise.

{schema_summary}

If the user asks about the data/tables, give a brief business-friendly overview.
Use this format for welcome messages:
TITLE: [Short title]
[1-2 sentence greeting]
INSIGHTS:
- **[Topic]** | [Description] | high
- **[Topic]** | [Description] | medium
QUESTIONS:
- [Specific answerable question]?
- [Another question]?

For short replies (yes/no/acknowledgment), just respond naturally without the format above.
Never mention raw SQL, table names, or column names — use business language."""

    messages = [SystemMessage(content=prompt)]

    # Add last 3 history messages for context (minimal)
    if history:
        _role_map = {"user": "human", "assistant": "ai"}
        for h in history[-3:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            # Truncate long assistant responses
            if role == "assistant" and len(content) > 200:
                content = content[:200] + "..."
            if role == "user":
                messages.append(HumanMessage(content=content))
            else:
                from langchain_core.messages import AIMessage
                messages.append(AIMessage(content=content))

    messages.append(HumanMessage(content=question))

    llm = get_worker_llm()  # Haiku — cheapest model
    response = await llm.ainvoke(messages)
    return response.content.strip()
