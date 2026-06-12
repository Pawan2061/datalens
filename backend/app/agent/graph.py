from __future__ import annotations

import asyncio
import json
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.agent.models import AgentEvent, AgentEventType
from app.agent.prompts import build_system_prompt
from app.agent.schema_cache import schema_cache
from app.agent.step_timer import StepTimer
from app.config import settings
from app.agent.api_tool_cache import (
    get_cached_workspace_api_tools,
    set_cached_workspace_api_tools,
)
from app.agent.tools import (
    ask_clarification,
    execute_sql,
    refresh_schema,
)
from app.agent.tools.sql_executor import _customer_scope_ctx, _customer_scope_field_ctx
from app.agent.tools.api_tool_factory import build_workspace_api_tools, describe_api_tools_for_prompt
from app.llm.openai_llm import get_planner_llm, get_synthesis_llm


ALL_TOOLS = [
    refresh_schema,
    ask_clarification,
    execute_sql,
]

def _cache_creation_from(details: dict) -> int:
    """Extract cache-write tokens from a LangChain ``input_token_details`` dict.

    langchain-anthropic >=1.4 zeroes out ``cache_creation`` whenever the API
    returned a TTL breakdown and instead reports counts under
    ``ephemeral_5m_input_tokens`` / ``ephemeral_1h_input_tokens``. The library
    guarantees the generic key is 0 when the TTL keys are populated, so summing
    all three is safe and works across both response shapes.
    """
    return (
        (details.get("cache_creation") or 0)
        + (details.get("ephemeral_5m_input_tokens") or 0)
        + (details.get("ephemeral_1h_input_tokens") or 0)
    )


# ── Streaming synthesis ───────────────────────────────────────────────
# Separator between narrative and metadata JSON in the LLM output.
_STREAM_SEP = "===METADATA==="

_STREAMING_SYNTHESIS_PROMPT = """\
You are a data assistant. Present query results as clean data tables — no executive summaries.

LANGUAGE & TONE — MIRROR THE USER:
- Detect language from the user's question (passed in the input). If it is Hinglish
  (Hindi in Latin script mixed with English, e.g. "pichle mahine ka revenue kya tha?"),
  write the narrative, title, key_findings, and follow_up_questions in the SAME
  Hinglish style. Do NOT switch to pure Devanagari Hindi or pure English.
- If the question is in English, respond in English.
- Match their register: casual questions → conversational tone, formal questions →
  professional tone, short questions → concise answers.
- Currency symbols, numeric formatting, and JSON keys stay the same in all languages.

CURRENCY & NUMBER FORMATTING (MANDATORY — GET THE MATH RIGHT):
- All monetary values in the query results are in INR (full RUPEES — not thousands,
  not lakhs). Always render with ₹, never $ or USD.
- EXACT UNIT MATH — memorize these (common source of mistakes):
    • 1 Crore (Cr) = 1,00,00,000 rupees = 10,000,000 rupees (SEVEN zeros, 10⁷)
    • 1 Lakh  (L)  = 1,00,000    rupees = 100,000    rupees (FIVE  zeros, 10⁵)
    • 1 Million ≠ 1 Crore. 1 Crore = 10 Million. DO NOT confuse them.
- FORMULAS (use these exactly — do NOT divide by 1,000,000 for Cr):
    • crores = rupees / 10,000,000   (round to 2 decimals)
    • lakhs  = rupees / 100,000      (round to 2 decimals)
- WORKED EXAMPLES — verify your output against these before emitting:
    • 88,742,903  → 88,742,903 / 10,000,000 = 8.87 Cr   (NOT 88.74)
    • 96,382,687  → 96,382,687 / 10,000,000 = 9.64 Cr   (NOT 96.38)
    • 35,093,154  → 35,093,154 / 10,000,000 = 3.51 Cr   (NOT 35.09)
    • 11,658,333  → 11,658,333 / 10,000,000 = 1.17 Cr   (NOT 11.66)
    •  8,86,902   →    886,902 /    100,000 = 8.87 L
    •    12,500   →                         = ₹12,500   (below 1 L)
- THRESHOLDS:
    ≥ 1,00,00,000 (10⁷) → show in Cr with 2 decimals (e.g. ₹8.87 Cr)
    ≥    1,00,000 (10⁵) → show in L  with 2 decimals (e.g. ₹8.87 L)
    otherwise           → show full rupee value with Indian commas (₹X,XX,XXX)
- SELF-CHECK before emitting ANY Cr or L value:
    1. Identify the raw rupee value from the query result.
    2. Divide by 10,000,000 (Cr) or 100,000 (L) — count the zeros carefully.
    3. If your formatted value × 10,000,000 doesn't match the raw value (for Cr),
       you made an error — redo the math before writing the narrative.
- Apply this to ALL amounts in the narrative, key_findings, titles, and tables.

TIME PERIOD — ALWAYS STATE IT:
- Every sales / revenue / quantity summary line MUST name the time period it
  covers: take it from the user's question ("April 2026", "FY 2026-27",
  "last 3 months: Mar–May 2026") or from date values in the data (MIN/MAX
  invoice_date columns if present). If no period is identifiable, append
  "(all available data)".
- Examples: "April 2026 revenue: ₹12.34 Cr across 1,240 invoices."
  "Paris collection sales (Apr 2025 – Mar 2026): 12,480 m across 312 invoices."

METERS vs REVENUE — NEVER SUBSTITUTE ONE FOR THE OTHER:
- If the user asked for sales in meters / quantity ("sales by meters",
  "kitna meter bika", "qty"), the headline figure MUST come from a quantity
  column (mtrs / order_qty / total_meters / qty) and be formatted in meters — NEVER
  a ₹ amount. If the data has no quantity column, say so explicitly instead
  of substituting revenue.
- For sales of a collection / product / design / item, lead with the quantity
  (meters) figure; mention revenue only if the user asked for it or the data
  was clearly queried for revenue.
- SELF-CHECK before emitting: a number labeled meters/m must NOT carry ₹ and
  must NOT come from an amount/revenue column — and vice versa.

PRESENTATION — LABELS & SORTING (apply to every table):
- Monetary sales figures are labeled "Amount" — header the column "Amount (₹)",
  NEVER "Revenue" / "Total Revenue". (Display label only — the value is still
  computed per the revenue rules.)
- Quantity-in-meters columns are labeled "Mtrs"; in prose write meters as
  "mtrs" (e.g. "12,480 mtrs").
- ALWAYS sort table rows before rendering — never emit rows in arbitrary order:
  • rankings / breakdowns → primary metric DESCENDING
  • time series → chronological (oldest → newest)
  • listings (invoices, pieces, orders) → date DESCENDING unless the user
    asked for a different order
  If the data arrives unsorted, re-sort it yourself before building the table.

AGGREGATE VALUES — USE PRE-COMPUTED TOTALS (CRITICAL):
- Each result may include a `numeric_totals` field with the EXACT sum of every numeric
  column across ALL rows in the dataset (not just the sample in `data`).
- ALWAYS use `numeric_totals` values when reporting totals, outstanding amounts, balances,
  or any aggregate figure. NEVER recalculate by summing the rows in `data` — the sample
  may be capped and will produce a WRONG partial total for large result sets.
- Example: if `numeric_totals.OUTSTANDING_AMOUNT = 2641379` then the total is ₹26.41 L,
  even if only 50 of 242 rows are visible in `data`.
- If `numeric_totals` is absent, note that figures are based on a sample.

CATEGORY / STATUS COUNTS — USE PRE-COMPUTED BREAKDOWN (CRITICAL):
- A result may include a `category_counts` field: for each low-cardinality text
  column (e.g. STATUS) it gives the EXACT count of every distinct value across
  ALL rows, not just the sample in `data`.
- For "how many <status>?", "kitne pending / rejected / cancelled?", or any
  breakdown by a category, ALWAYS read `category_counts`. NEVER count occurrences
  in `data` — it is capped and will undercount large result sets (e.g. the
  relevant rows may sit past the first 50).
- Map the user's intent to the right value(s). For order/shipment STATUS,
  "pending" / "kitne pending" = orders still in progress: STATUS = "UNDER PROCCESS".
  COMPLETE = already dispatched/done; REJECTED and CANCELLED are NOT pending —
  never count them as pending.
- Example: `category_counts.STATUS = {"COMPLETE": 130, "UNDER PROCCESS": 2,
  "REJECTED": 2, "CANCELLED": 1}` and the user asks "kitne orders pending hai?"
  → "2 orders pending hain (UNDER PROCCESS)", even if only 50 of 135 rows show in `data`.

FABRIC STOCK — SINGLE-ROLL LENGTH AVAILABILITY (MANDATORY when it applies):
- APPLIES when the data has a per-piece meters column (PIECE_DISPVAL, or PIECE_VALUE)
  AND the user asks whether a specific length N is available — e.g. "N m hai kya?",
  "N meter milega?", "N mtr available?", "do you have N m?", "N meter chahiye".
- Each row is ONE physical roll. Fabric is cut from ONE continuous roll, so you CANNOT
  make an N-meter cut by adding two shorter rolls.
- THE ONLY VALID TEST: N meters is available IF AND ONLY IF the longest single roll,
  `numeric_maxes.PIECE_DISPVAL` (fall back to `numeric_maxes.PIECE_VALUE`), is >= N.
  Use `numeric_maxes` for this — NEVER `numeric_totals` (the SUM), and NEVER require a
  roll exactly equal to N.
- YOUR SUMMARY LINE MUST OPEN WITH A YES/NO VERDICT — it is FORBIDDEN to lead with
  "Total stock: X m" for a length question. Mirror the user's language (Hinglish → Hinglish):
    • max >= N  → "Haan, <N> m available hai." Then name a qualifying roll (the smallest
      row whose meters >= N) with its warehouse. Total stock may follow as context only.
    • max < N but `numeric_totals` >= N, and the user did NOT demand a single piece →
      "Single continuous piece nahi hai, lekin chhote pieces jod ke ban sakta hai
      (alag-alag rolls)." Mention the longest roll and the total.
    • max < N and the user demanded a single piece ("single piece", "ek piece", "ek than",
      "continuous") → "Nahi, single piece mein nahi — sabse bada roll <max> m hai."
    • `numeric_totals` < N → "Nahi, total stock hi sirf <total> m hai."
- WORKED EXAMPLE: rows have PIECE_DISPVAL values [96.7, 6.8, 4.4, 3.7, ...], total 262.55,
  user asks "60 m hai kya?". `numeric_maxes.PIECE_DISPVAL = 96.7 >= 60` →
  "Haan, 60 m available hai (96.7 m ka roll, Boisar se cut hoga)." Replying "60 m nahi" or
  leading with "Total stock 262.55 m" here is WRONG — a 96.7 m roll covers 60 m.

OUTSTANDING / BALANCE COLUMN SELECTION (apply when reporting receivables):
- If the result contains `primary_balance_total`, that IS the outstanding total — use it
  directly. Do NOT pick any other column. Do NOT recalculate. Just format and quote it.
  (`primary_balance_column` names the source column for transparency if you want to mention it.)
- Only if `primary_balance_total` is absent: look in `numeric_totals` for a balance-like
  column name and use that. Column name hints:
  • Balance / BALANCE / OUTSTANDING_AMOUNT / REMAINING_AMOUNT → USE THIS for outstanding total
  • Amount / AMOUNT / INVOICE_AMOUNT / TOTAL_AMOUNT → original billed amount, NOT outstanding
- The difference between the two is partial payments already received.
- NEVER add up individual row values to compute the outstanding total — partial rows give wrong sums.

ANSWER BREVITY — ONE-LINER QUESTIONS (overrides DATA-FIRST Step 2):
- If the user asked ONLY for the outstanding/overdue/balance amount ("what's my
  outstanding?", "kitna baki hai?", "mera outstanding kitna hai?") WITHOUT asking for a
  list / details / breakdown / invoice-wise / "kaunse invoice":
  → Respond with the ONE summary line only (use primary_balance_total). NO table.
  → Set "display": "answer_only" in the metadata JSON.
- If the user asked a yes/no question (dispatched? / bhej diya? / available hai? /
  "N m hai kya?"):
  → Open with the one-line verdict answer. Add a table ONLY if multiple matching
    items/orders make it genuinely necessary, or the user asked for details.
  → If no table follows, set "display": "answer_only".
- Render the detailed table when the user explicitly asks for details / list /
  breakup / invoice-wise — then use "display": "full".

FABRIC ITEM NAMING:
- Identify fabric items as "<Collection> <Sr. No.>" (e.g. "Cuban 12") in prose and tables.
- The serial column header is "Sr. No." — NEVER "Item No." / "ITEM_NO". Rename it in
  output tables.

LISTING / TABULAR REQUESTS — WHEN USER SAYS "LIST", "SHOW", "DISPLAY", "DIKHA", "BATAO":
- If the user explicitly asked to list, show, or display records, output a markdown table
  using the rows in `data`. Do NOT replace a listing request with a prose summary.
- Lead with a one-line total (using `numeric_totals` for accuracy), then render the table.
- If `row_count` > 50, add a note: "Showing first 50 of {row_count} records."
- Choose meaningful columns for the table (invoice number, date, amount, customer, etc.).
  Omit internal IDs and audit fields unless the user asked for them.

INTERNAL VALIDATION (do silently before writing the narrative):
- Cross-check that totals ≈ avg × count and that percentages sum sensibly.
- If numbers look inconsistent across sub-results, flag it briefly. Do NOT fabricate reconciliations.
- Never invent a figure the data does not contain.

OUTPUT — two parts:

PART 1 — NARRATIVE (markdown):

DATA-FIRST FORMAT — follow this order strictly for every response with data:

Step 1 — ONE summary line only.
  Write a single short sentence with the key total / metric AND the time period
  it covers (per TIME PERIOD rule). Use numeric_totals for accuracy.
  Apply INR formatting rules. Examples:
    "Total outstanding: ₹68.13 L across 248 invoices."
    "April 2026 revenue: ₹12.34 Cr across 1,240 invoices."
    "Paris collection sales (Apr 2025 – Mar 2026): 12,480 m across 312 invoices."
    "Paris collection stock: 342.5 m across 18 pieces."
  DO NOT write paragraphs, executive summaries, or analytical prose. One line only.

Step 2 — MARKDOWN TABLE of the data (immediately after the summary line).
  SKIP this step entirely when the ANSWER BREVITY rule above applies (bare
  outstanding-amount or yes/no questions) — the summary line IS the answer.
  • Render ALL visible rows from `data` as a markdown table.
  • Choose the most useful columns: invoice number, date, customer, amount, status, etc.
  • Apply INR formatting to all monetary values in the table cells.
  • Omit internal system fields (IDs, audit timestamps) unless the user asked for them.
  • If row_count > len(data): add one line after the table: "Showing first {len(data)} of {row_count} records."

For multi-part questions (sub_questions present): one ## header per sub-question,
then summary line + table under each. No "Putting It Together" section.

STOP after the table(s). No follow-up questions, suggestions, or calls-to-action in the narrative.

No emojis. No filler adjectives. Let the data speak.

Then output this separator on its own line:
===METADATA===

PART 2 — JSON (after separator, no markdown fences):
{
  "title": "Short descriptive title (e.g. 'Outstanding Invoices — Floor & Furnishing India')",
  "key_findings": [],
  "follow_up_questions": ["Specific drill-down question?"],
  "display": "full"
}

Rules: key_findings should be empty array [] for data/tabular responses. 1-2 follow-up questions max.
"display" is "answer_only" when the narrative is intentionally a one-liner without a
table (per ANSWER BREVITY) — this hides chart/table cards in the UI. Otherwise "full".
Every number must come from the data.
Output ONLY the narrative, then the separator, then the JSON. No preamble.
"""

# Appended to the synthesis prompt ONLY for customer-scoped chats. Admin chats
# keep the strict data-only format unchanged.
_CUSTOMER_SUMMARY_ADDENDUM = """

CUSTOMER CHAT WRAP-UP (this is a customer-scoped chat — applies on top of all rules above):
- AFTER the table(s), add ONE crisp, friendly wrap-up of 1-2 short sentences in
  PART 1, summarizing what the result means for the customer, in the user's
  language (Hinglish → Hinglish). This is the ONLY exception to the
  "STOP after the table(s)" rule.
- Conversational but strictly factual — restate the headline insight simply
  (e.g. "Aapka total outstanding ₹2.93 L hai, jismein sabse purana invoice
  March 2026 ka hai." or "In short, your Paris collection sold 12,480 mtrs
  this FY — your highest-moving collection."). Every number must come from
  the data.
- Maximum 2 sentences. No recommendations, no marketing tone, no follow-up
  questions, no emojis.
- For one-liner answers (ANSWER BREVITY), add at most ONE extra conversational
  sentence after the answer line — the answer line itself stays first.
"""


async def _stream_synthesis(
    question: str,
    sub_results: list[dict],
    queue: asyncio.Queue | None,
    plan: dict | None = None,
    customer_scoped: bool = False,
) -> dict | None:
    """Stream synthesis narrative tokens as SSE events, return full synthesis dict.

    Tokens before ===METADATA=== are emitted as narrative_chunk events so the
    frontend can display the narrative word-by-word while the LLM generates it.
    After the separator, the JSON metadata is collected silently.

    ``customer_scoped`` appends the conversational wrap-up addendum for
    customer-view chats; admin chats keep the strict data-only format.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Only include rows with data
    clean_results = []
    for r in sub_results:
        if r.get("error"):
            continue
        all_data = r.get("data", [])
        # For API results, numeric_totals are pre-computed from ALL rows in
        # api_tool_factory before the 25-row LLM cap — use those directly so
        # we don't overwrite accurate totals with partial sums from capped data.
        # For SQL results (no pre-computed totals), compute from all_data which
        # contains the full result set before our own 50-row cap below.
        if r.get("numeric_totals"):
            numeric_totals: dict = r["numeric_totals"]
        else:
            numeric_totals = {}
            if all_data:
                for col in (all_data[0] or {}).keys():
                    vals = [row.get(col) for row in all_data if isinstance(row.get(col), (int, float))]
                    if vals:
                        numeric_totals[col] = round(sum(vals), 2)
        # numeric_maxes = the single largest value per numeric column. For
        # fabric, MAX(PIECE_DISPVAL) is the longest single roll and is the ONLY
        # correct test for "is N meters available?" (a cut comes from one roll,
        # never summed). Pre-computed in api_tool_factory across ALL rows; for
        # SQL results compute from all_data.
        if r.get("numeric_maxes"):
            numeric_maxes: dict = r["numeric_maxes"]
        else:
            numeric_maxes = {}
            if all_data:
                for col in (all_data[0] or {}).keys():
                    vals = [row.get(col) for row in all_data if isinstance(row.get(col), (int, float))]
                    if vals:
                        numeric_maxes[col] = round(max(vals), 2)
        # Categorical breakdown (e.g. STATUS counts) pre-computed across ALL
        # rows in api_tool_factory before the row cap. Surfaced so the synthesis
        # LLM can answer "how many pending / rejected?" without counting only
        # the visible (capped) rows. API-only; absent for SQL results.
        category_counts: dict = r.get("category_counts") or {}
        entry: dict = {
            "description": r.get("description", ""),
            "columns": r.get("columns", []),
            "data": all_data[:100],   # cap rows to avoid huge prompts
            "row_count": r.get("row_count", len(all_data)),
        }
        if numeric_totals:
            entry["numeric_totals"] = numeric_totals
        if numeric_maxes:
            entry["numeric_maxes"] = numeric_maxes
        if category_counts:
            entry["category_counts"] = category_counts
        clean_results.append(entry)

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
        system_content = _STREAMING_SYNTHESIS_PROMPT
        if customer_scoped:
            system_content += _CUSTOMER_SUMMARY_ADDENDUM
        messages = [
            SystemMessage(content=system_content),
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
            "display": metadata.get("display", "full"),
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
    customer_scope_name: str = "",
    customer_scope_field: str = "customer_id",
) -> dict | None:
    """Run the LangGraph ReAct agent and stream SSE events.

    Events are pushed to ``queue`` for the SSE streaming endpoint.  The final
    InsightResult dict is also returned so callers (e.g. the chat route) can
    persist it without having to re-read the queue.
    """
    start_time = time.perf_counter()
    timer = StepTimer()

    # ── Quick response check (saves LLM call entirely) ───────────
    from app.agent.quick_responses import detect_quick_response, response_cache

    with timer.step("quick_response_check"):
        quick = detect_quick_response(question)
    if quick:
        total_duration = (time.perf_counter() - start_time) * 1000
        final = _build_conversational_result(
            quick, total_duration, step_timings=timer.as_dict(),
        )
        await _emit(queue, AgentEventType.final_result, final)
        await _emit_done(queue)
        return final

    # ── Response cache check ─────────────────────────────────────
    # Cache key MUST include scope/mode/tables — otherwise admin answers
    # can be served to a scoped customer view (data leak) and quick/deep
    # results collide with each other.
    with timer.step("cache_lookup"):
        cached = response_cache.get(
            question,
            connection_id,
            customer_scope=customer_scope,
            analysis_mode=analysis_mode,
            selected_tables=selected_tables,
        )
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
            cached_copy["execution_metadata"]["step_timings"] = timer.as_dict()
        await _emit(queue, AgentEventType.final_result, cached_copy)
        await _emit_done(queue)
        return cached_copy

    # ── Chit-chat → cheap model (Haiku) ─────────────────────────────
    from app.agent.quick_responses import is_conversational
    if is_conversational(question, has_history=bool(history)):
        import logging as _conv_log
        _conv_log.getLogger(__name__).info(
            "[agent] routing to cheap conversational path question=%r "
            "workspace=%s scope=%r — API tools will NOT be callable on this turn",
            (question or "")[:120], workspace_id, customer_scope or "admin",
        )
        await _emit(queue, AgentEventType.thinking, {
            "step": "conversational",
            "content": "Processing your message...",
        })
        try:
            with timer.step("conversational_path"):
                response_text = await _run_cheap_conversational(
                    question, connection_id, workspace_id, history,
                )
            total_duration = (time.perf_counter() - start_time) * 1000
            final = _build_conversational_result(
                response_text, total_duration,
                step_timings=timer.as_dict(),
            )
            response_cache.put(
                question,
                connection_id,
                final,
                customer_scope=customer_scope,
                analysis_mode=analysis_mode,
                selected_tables=selected_tables,
            )
            await _emit(queue, AgentEventType.final_result, final)
            await _emit_done(queue)
            return final
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

        with timer.step("schema_profile_load"):
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
        with timer.step("schema_profile_load"):
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

    # Append API tool descriptions to the prompt so the LLM knows about them.
    # The scope is passed through so the description explicitly flags
    # customer-slot params as auto-filled (customer mode) or requires the
    # LLM to confirm a specific customer (admin mode).
    if api_tool_configs:
        system_prompt += describe_api_tools_for_prompt(
            api_tool_configs,
            customer_scope=customer_scope,
            customer_scope_name=customer_scope_name,
        )

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
        with timer.step("pre_plan"):
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
        display_name = customer_scope_name or customer_scope
        scope_field = customer_scope_field or "customer_id"
        scope_addendum = (
            f"\n\n━━ CUSTOMER SCOPE FILTER ━━\n"
            f"You are operating in CUSTOMER mode. The user is viewing as: {display_name}.\n"
            f"{scope_field} = {customer_scope}\n"
            f"CRITICAL: Every SQL query that touches `invoice` or `customer_master` "
            f"MUST include a WHERE clause (or a filter inside EVERY CTE/subquery that "
            f"reads those tables) restricting results to {scope_field} = '{customer_scope}'. "
            f"This is enforced at the execution layer — a query that does not pin "
            f"{scope_field} to '{customer_scope}', or that uses {scope_field} with "
            f"IN (subquery), != , <> or NOT IN, or that filters by another customer's "
            f"name / city / state instead, will be REJECTED and you must retry.\n"
            f"Tables that do NOT carry customer data (e.g. stock, item_master) do not need "
            f"the filter — they represent shared inventory visible to all customers.\n"
            f"NEVER return invoice or customer_master rows for any customer other than "
            f"'{display_name}' ({scope_field} = '{customer_scope}'), and never aggregate "
            f"across multiple customers.\n"
            f"FOR EXTERNAL API TOOLS: Any input parameter that names the customer "
            f"(customer_id, CUSTOMER_CODE, cust_id, etc.) is pre-filled with "
            f"'{customer_scope}'. Call the tool directly — DO NOT ask the user for "
            f"their customer ID, and DO NOT overwrite it with a different value.\n"
            f"IMPORTANT: The customer context is already set to '{display_name}'. "
            f"Do NOT ask the user which customer they mean — all questions refer to this customer.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
    else:
        scope_addendum = (
            f"\n\n━━ ADMIN MODE ━━\n"
            f"You are operating in ADMIN mode — unrestricted view across ALL customers.\n"
            f"For SQL: do NOT apply any customer_id filter. Return data for all customers "
            f"unless the user explicitly names a specific one in their current message.\n"
            f"For external API tools that REQUIRE a customer_id: if the user asks a "
            f"'my/our'-style question without naming a customer, ask them which customer "
            f"(or subset) they want. If they named a customer, pass that customer's ID "
            f"into the tool explicitly.\n"
            f"Ignore any customer scope references from prior conversation turns.\n"
            f"━━━━━━━━━━━━━━━━\n"
        )

    # Diagnostic trace — lets admins correlate a question to the scope the
    # agent actually ran with (and to the resulting API-tool URLs logged by
    # api_tool_factory below).
    import logging as _logging
    _logging.getLogger(__name__).info(
        "[agent] run question=%r workspace=%s connection=%s scope=%r (%s) "
        "api_tools=%d mode=%s",
        (question or "")[:120], workspace_id, connection_id,
        customer_scope or "admin", customer_scope_name or "-",
        len(api_tool_configs or []), analysis_mode,
    )

    # Split the prompt into a stable prefix (rules + workspace profile +
    # API tool descriptions) and a dynamic suffix (scope + per-question plan).
    # The prefix is what we'd cache with Anthropic prompt caching; the suffix
    # must stay OUT of the cache key so each turn reflects the current scope
    # and plan. For non-Anthropic providers we concatenate both into a single
    # string — behavior is identical to before.
    static_prefix = system_prompt
    dynamic_suffix = scope_addendum + plan_addendum
    agent_prompt = static_prefix + dynamic_suffix

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

    # Build dynamic API tools for this workspace and merge with built-in tools.
    # Forward the scope so customer-slot params auto-fill in customer view.
    dynamic_api_tools = (
        build_workspace_api_tools(
            api_tool_configs,
            workspace_id=workspace_id or "",
            customer_scope=customer_scope,
            customer_scope_name=customer_scope_name,
        )
        if api_tool_configs else []
    )
    all_tools = ALL_TOOLS + dynamic_api_tools
    # Track dynamic tool names for result handling
    dynamic_tool_names = {t.name for t in dynamic_api_tools}

    # ── Prompt caching (Anthropic only, feature-flagged) ───────────────
    # When active, we mark the static prefix with cache_control=ephemeral so
    # subsequent turns in the 5-min window pay 0.1x for those tokens. The
    # dynamic suffix is appended as a separate, uncached block so scope/plan
    # changes don't invalidate the cache.
    prompt_arg = _build_cached_prompt_arg(
        static_prefix=static_prefix,
        dynamic_suffix=dynamic_suffix,
        fallback_prompt=agent_prompt,
    )

    graph = create_react_agent(
        model=llm,
        tools=all_tools,
        prompt=prompt_arg,
    )

    # Stream through the agent's execution
    sub_query_index = 0
    all_sub_results: list[dict] = []
    agent_final_text = ""  # Capture the agent's last text response
    # Token usage tracking
    # input_tokens / output_tokens follow Anthropic semantics: input_tokens is
    # FRESH input only (excludes cache reads and cache writes). Cache buckets
    # are tracked separately so the UI can show all four.
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_read_tokens = 0
    total_cache_creation_tokens = 0
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

    # Pin the customer scope into the contextvar so execute_sql can enforce
    # it as a hard guard independent of whatever SQL the LLM generates.
    # The token ensures we restore the previous value even if this coroutine
    # is nested (e.g. a refresh running inside another agent call).
    _scope_token = _customer_scope_ctx.set(customer_scope or "")
    _scope_field_token = _customer_scope_field_ctx.set(customer_scope_field or "customer_id")
    agent_loop_start = time.perf_counter()
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
                        details = um.get('input_token_details') or {}
                        total_cache_read_tokens += details.get('cache_read', 0) or 0
                        total_cache_creation_tokens += _cache_creation_from(details)
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
                        # Record what we have so the analytics row carries
                        # real duration / token / step-timing data instead of
                        # silently saving zeros.
                        timer.add(
                            "agent_loop",
                            (time.perf_counter() - agent_loop_start) * 1000,
                        )
                        clarification_total = (time.perf_counter() - start_time) * 1000
                        return {
                            "summary": {
                                "title": "Clarification requested",
                                "narrative": clarification_text,
                                "key_findings": [],
                                "follow_up_questions": [],
                            },
                            "charts": [],
                            "tables": [],
                            "execution_metadata": {
                                "total_duration_ms": round(clarification_total, 2),
                                "sub_query_count": sub_query_index,
                                "total_rows": 0,
                                "input_tokens": total_input_tokens,
                                "output_tokens": total_output_tokens,
                                "total_tokens": total_input_tokens + total_output_tokens,
                                "cache_read_tokens": total_cache_read_tokens,
                                "cache_creation_tokens": total_cache_creation_tokens,
                                "model_name": model_name,
                                "estimated_cost_usd": _estimate_cost(
                                    total_input_tokens, total_output_tokens, model_name,
                                    cache_read_tokens=total_cache_read_tokens,
                                    cache_creation_tokens=total_cache_creation_tokens,
                                ),
                                "step_timings": timer.as_dict(),
                            },
                        }

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
                        details = um.get('input_token_details') or {}
                        total_cache_read_tokens += details.get('cache_read', 0) or 0
                        total_cache_creation_tokens += _cache_creation_from(details)
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
        timer.add("agent_loop", (time.perf_counter() - agent_loop_start) * 1000)

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

            partial = {
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
                    "cache_read_tokens": total_cache_read_tokens,
                    "cache_creation_tokens": total_cache_creation_tokens,
                    "model_name": model_name,
                    "estimated_cost_usd": 0.0,
                    "step_timings": timer.as_dict(),
                },
            }
            await _emit(queue, AgentEventType.final_result, partial)
            await _emit_done(queue)
            return partial
        # Fall through to build partial results from whatever we collected
    else:
        timer.add("agent_loop", (time.perf_counter() - agent_loop_start) * 1000)
    finally:
        _customer_scope_ctx.reset(_scope_token)
        _customer_scope_field_ctx.reset(_scope_field_token)

    # ── Streaming synthesis (runs after the agent finishes all SQL) ──
    # analyze_results is no longer an agent tool — synthesis runs here so
    # we can stream the narrative token-by-token before the final result.
    if all_sub_results and not synthesis_output:
        try:
            with timer.step("synthesis"):
                synthesis_output = await _stream_synthesis(
                    question, all_sub_results, queue, plan=plan,
                    customer_scoped=bool(customer_scope),
                )
        except Exception:
            pass  # Synthesis failure → heuristic fallback in _build_final_result

    # ── Build final result ───────────────────────────────────────────
    total_duration = (time.perf_counter() - start_time) * 1000

    with timer.step("build_result"):
        # If no queries were executed, the agent responded conversationally
        if sub_query_index == 0 and agent_final_text:
            final_result = _build_conversational_result(
                agent_final_text, total_duration,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_read_tokens=total_cache_read_tokens,
                cache_creation_tokens=total_cache_creation_tokens,
                model_name=model_name,
                step_timings=timer.as_dict(),
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
                cache_read_tokens=total_cache_read_tokens,
                cache_creation_tokens=total_cache_creation_tokens,
                model_name=model_name,
                step_timings=timer.as_dict(),
            )

    # ── Guardrail Layer 4: Response guard ────────────────────────
    from app.guardrails.response_guard import scrub_insight_result
    with timer.step("response_guard"):
        final_result = scrub_insight_result(final_result)

    # Update step_timings to include build_result + response_guard.
    if "execution_metadata" in final_result:
        final_result["execution_metadata"]["step_timings"] = timer.as_dict()

    # Cache the result for future similar questions.
    # Scope/mode/tables MUST be part of the key — see ResponseCache._normalize.
    response_cache.put(
        question,
        connection_id,
        final_result,
        customer_scope=customer_scope,
        analysis_mode=analysis_mode,
        selected_tables=selected_tables,
    )

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
                cache_read_tokens=meta.get("cache_read_tokens", 0),
                cache_creation_tokens=meta.get("cache_creation_tokens", 0),
                model_name=meta.get("model_name", ""),
            )
        except Exception:
            pass  # Don't fail chat if usage recording fails

    await _emit_done(queue)
    return final_result


def _build_conversational_result(
    agent_text: str,
    total_duration_ms: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    model_name: str = "",
    step_timings: dict[str, float] | None = None,
) -> dict:
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
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        model_name=model_name,
        estimated_cost_usd=_estimate_cost(
            input_tokens, output_tokens, model_name,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        ),
        step_timings=step_timings or {},
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
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    model_name: str = "",
    step_timings: dict[str, float] | None = None,
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
    # When synthesis deliberately answered with a one-liner (bare outstanding
    # amount, yes/no verdicts), suppress chart/table cards entirely — the
    # narrative line IS the answer. Absent/unknown values fall back to "full".
    answer_only = bool(synthesis and synthesis.get("display") == "answer_only")
    valid_chart_types = {ct.value for ct in ChartType}
    charts: list[ChartRecommendation] = []
    if agent_charts and not answer_only:
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
    if answer_only:
        charts = []
    elif not charts:
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
        if r.data and r.description not in charted_descriptions and not answer_only
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
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        model_name=model_name,
        estimated_cost_usd=_estimate_cost(
            input_tokens, output_tokens, model_name,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
        ),
        step_timings=step_timings or {},
    )

    result = InsightResult(
        summary=summary,
        charts=charts,
        tables=tables,
        execution_metadata=metadata,
    )
    return result.model_dump()


def _build_cached_prompt_arg(
    static_prefix: str,
    dynamic_suffix: str,
    fallback_prompt: str,
):
    """Return a prompt argument for create_react_agent.

    For Anthropic (when the feature flag is on and the prefix is large enough),
    returns a callable that emits a SystemMessage with a cache_control marker
    on the static prefix — subsequent turns reuse the cached prefix at 0.1x
    list input rate.

    For every other provider (or when caching is disabled / the prefix is too
    small), returns the plain concatenated string so behavior is IDENTICAL
    to the pre-caching implementation. No other code path changes.
    """
    # Gate on provider + feature flag. Token threshold uses a cheap
    # chars/4 estimate — good enough for "is this worth caching" decisions.
    eligible = (
        settings.llm_provider == "anthropic"
        and settings.anthropic_prompt_caching
        and static_prefix
        and (len(static_prefix) // 4) >= settings.anthropic_prompt_cache_min_tokens
    )
    if not eligible:
        return fallback_prompt

    def _cached_prompt(state):
        system_blocks: list[dict] = [
            {
                "type": "text",
                "text": static_prefix,
                "cache_control": {"type": "ephemeral"},
            },
        ]
        if dynamic_suffix:
            system_blocks.append({"type": "text", "text": dynamic_suffix})
        msgs: list = [SystemMessage(content=system_blocks)]
        msgs.extend(state.get("messages", []) or [])
        return msgs

    return _cached_prompt


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


def _estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model_name: str,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate USD cost based on token counts and model.

    ``input_tokens`` from langchain-anthropic is the *true* total
    (fresh + cache_read + cache_creation), so we subtract the cache portions
    before applying the 1x input price, then bill cache reads at 0.10x and
    cache writes at 1.25x. For non-Anthropic providers cache kwargs default
    to 0, so the formula collapses to fresh × input.
    """
    # Pricing per 1M tokens — sourced from
    # https://platform.claude.com/docs/en/about-claude/pricing.
    # Order matters: longer/more-specific keys first so e.g. "claude-opus-4-7"
    # wins over a shorter "claude-opus" prefix.
    _PRICING = (
        ("claude-sonnet-4-6", {"input": 3.0, "output": 15.0}),
        ("claude-sonnet-4-5", {"input": 3.0, "output": 15.0}),
        ("claude-sonnet-4-20250514", {"input": 3.0, "output": 15.0}),
        ("claude-sonnet-4", {"input": 3.0, "output": 15.0}),
        ("claude-opus-4-7", {"input": 5.0, "output": 25.0}),
        ("claude-opus-4-6", {"input": 5.0, "output": 25.0}),
        ("claude-opus-4-5", {"input": 5.0, "output": 25.0}),
        ("claude-opus-4-1", {"input": 15.0, "output": 75.0}),
        ("claude-opus-4-0", {"input": 15.0, "output": 75.0}),
        ("claude-opus-4", {"input": 15.0, "output": 75.0}),
        ("claude-haiku-4-5", {"input": 1.0, "output": 5.0}),
        ("claude-haiku-3-5", {"input": 0.8, "output": 4.0}),
        ("gpt-4o", {"input": 2.5, "output": 10.0}),
        ("gpt-4.1-mini", {"input": 0.4, "output": 1.6}),
        ("gemini-2.0-flash", {"input": 0.0, "output": 0.0}),
        ("gemini-2.5-flash", {"input": 0.0, "output": 0.0}),
        ("gemini", {"input": 0.0, "output": 0.0}),
    )
    model_lower = (model_name or "").lower()
    pricing = next(
        (p for key, p in _PRICING if key in model_lower),
        {"input": 1.0, "output": 5.0},
    )

    fresh_input = max(input_tokens - cache_read_tokens - cache_creation_tokens, 0)
    cost = (
        (fresh_input * pricing["input"] / 1_000_000)
        + (output_tokens * pricing["output"] / 1_000_000)
        + (cache_creation_tokens * pricing["input"] * 1.25 / 1_000_000)
        + (cache_read_tokens * pricing["input"] * 0.10 / 1_000_000)
    )
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
You are DataLens, a friendly AI data analyst assistant. The user is chatting casually.
Respond naturally in 1-3 sentences. Be warm, helpful, and concise.

LANGUAGE & TONE — MIRROR THE USER:
- If the user writes in Hinglish (Hindi in Latin script mixed with English,
  e.g. "kaise ho?", "data dikhao"), reply in the SAME Hinglish style.
  Do NOT switch to pure Devanagari Hindi or pure English.
- If the user writes in English, reply in English.
- Match their register: casual → casual, formal → formal, short → short.

{schema_summary}

If the user asks about the data/tables, give a brief business-friendly overview.
Use this format for welcome / capability messages:
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
