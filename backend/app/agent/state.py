from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State for the LangGraph ReAct agent."""

    messages: Annotated[list, add_messages]
