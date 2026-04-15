from __future__ import annotations

from langchain_core.tools import tool


@tool
def ask_clarification(question: str) -> str:
    """Ask the user a clarifying question when their request is ambiguous.

    Use this when you cannot determine what analysis to perform because the
    user's question is too vague or missing critical details (e.g., which
    metric, time period, or dimension to focus on).

    Args:
        question: The clarifying question to ask the user.

    Returns:
        A signal string that the agent loop intercepts and sends to the frontend.
    """
    return f"CLARIFICATION_NEEDED: {question}"
