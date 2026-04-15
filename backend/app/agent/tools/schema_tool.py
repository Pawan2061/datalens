from __future__ import annotations

from langchain_core.tools import tool

from app.agent.schema_cache import schema_cache


@tool
async def refresh_schema(connection_id: str) -> str:
    """Re-fetch the database schema from the live database.

    Use this ONLY if you encounter errors suggesting the schema may have
    changed (e.g., unknown table or column errors). The schema is already
    provided in your system prompt for normal use.

    Args:
        connection_id: The database connection identifier.

    Returns:
        The updated schema as formatted text.
    """
    schema_cache.invalidate(connection_id)
    return await schema_cache.get(connection_id)
