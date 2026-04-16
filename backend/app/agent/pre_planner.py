"""Pre-planner: decomposes complex questions into a structured execution plan.

Uses Gemini Flash (free) to analyze the user's question BEFORE the ReAct
agent runs. This gives Haiku (the cheap execution model) a clear roadmap
instead of relying on it to decompose complex multi-part questions itself.
"""
from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.openai_llm import get_synthesis_llm

logger = logging.getLogger(__name__)

# Keywords that signal a question likely needs multi-step decomposition.
# Questions without these (or that are very short) go straight to the agent.
_COMPLEX_SIGNALS = [
    "vs", "versus", "compare", "comparison",
    "top ", "trend", "over time",
    "by month", "by quarter", "by year", "by week",
    "breakdown", "distribution", "correlation",
    "and also", "and then", "for each",
    "per ", "across ", "between ",
    "how does", "how do", "what is the relationship",
    "rank", "ranking", "segment", "segmentation",
]


def _should_pre_plan(question: str) -> bool:
    """Fast heuristic — skip the LLM pre-planner for obviously simple questions.

    Returns True only if the question looks complex enough to benefit from
    decomposition. This avoids a full LLM round-trip (~500-1500 ms) for the
    majority of single-query questions.

    Threshold raised to 12 words (was 8) — questions under 12 words are nearly
    always single-query even when they contain comparison keywords.
    """
    q = question.lower()
    words = q.split()
    # Very short questions are almost always single-query
    if len(words) < 12:
        return False
    # At least one complexity signal must be present
    return any(signal in q for signal in _COMPLEX_SIGNALS)

_PRE_PLAN_PROMPT = """\
You are a data analysis planner. Given a user question and a database schema,
decompose the question into a concrete execution plan.

OUTPUT FORMAT — JSON only, no markdown fences:
{
  "complexity": "simple" | "moderate" | "complex",
  "sub_questions": [
    {
      "question": "The specific sub-question to answer",
      "approach": "Brief SQL strategy (e.g. 'GROUP BY month, SUM revenue')",
      "depends_on": []  // indices of sub-questions this depends on (empty = independent)
    }
  ],
  "combination_strategy": "How to combine the results into a coherent answer",
  "suggested_charts": ["chart_type_1", "chart_type_2"]
}

RULES:
- "simple" = 1 query answers it. "moderate" = 2-3 queries. "complex" = 4+ queries or nested logic.
- Each sub_question must be independently answerable with ONE SQL query.
- If the question asks "X of the top N by Y", break it into:
  1. First find top N by Y
  2. Then query X for those top N
- For trend questions with filters (e.g. "trend of top 10 customers"):
  1. First identify the entities (top 10 customers)
  2. Then query the trend data filtered to those entities
- For comparison questions (e.g. "A vs B"):
  1. Query A metrics
  2. Query B metrics (or combine into one GROUP BY query if same table)
- Keep sub_questions to a maximum of 5 — combine where possible.
- NEVER include actual SQL — just describe the approach in plain English.
- Output ONLY valid JSON.
"""


async def pre_plan(question: str, schema_summary: str) -> dict | None:
    """Decompose a question into a structured plan using Gemini Flash.

    Returns the plan dict, or None if planning fails or question is simple.
    Skips the LLM entirely for short/simple questions via a fast heuristic.
    """
    # Fast path — avoid LLM round-trip for obviously simple questions
    if not _should_pre_plan(question):
        return None

    try:
        llm = get_synthesis_llm()  # 2048-token cap — plan JSON is <500 tokens
        messages = [
            SystemMessage(content=_PRE_PLAN_PROMPT),
            HumanMessage(content=(
                f"Database schema:\n{schema_summary[:3000]}\n\n"
                f"User question: {question}"
            )),
        ]
        response = await llm.ainvoke(messages)
        text = response.content.strip()

        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            text = "\n".join(lines).strip()

        plan = json.loads(text)

        # Only return plan for non-simple questions
        if plan.get("complexity") == "simple":
            return None

        return plan
    except Exception as e:
        logger.warning("Pre-planner failed (falling back to direct agent): %s", e)
        return None


def format_plan_for_agent(plan: dict) -> str:
    """Format a pre-plan into instructions the ReAct agent can follow."""
    if not plan:
        return ""

    parts = [
        "\n══ PRE-PLANNED EXECUTION ROADMAP ══",
        f"Complexity: {plan.get('complexity', 'moderate')}",
        f"Strategy: {plan.get('combination_strategy', '')}",
        "",
        "Sub-questions to execute IN ORDER:",
    ]

    for i, sq in enumerate(plan.get("sub_questions", [])):
        deps = sq.get("depends_on", [])
        dep_note = f" (after completing #{', #'.join(str(d+1) for d in deps)})" if deps else ""
        parts.append(f"  {i+1}. {sq['question']}{dep_note}")
        parts.append(f"     Approach: {sq.get('approach', '')}")

    suggested = plan.get("suggested_charts", [])
    if suggested:
        parts.append(f"\nSuggested visualizations: {', '.join(suggested)}")

    parts.append(
        "\nIMPORTANT: Follow this plan step by step. Execute each sub-question's query, "
        "then combine results using analyze_results + recommend_charts_tool.\n"
        "══════════════════════════════════\n"
    )

    return "\n".join(parts)
