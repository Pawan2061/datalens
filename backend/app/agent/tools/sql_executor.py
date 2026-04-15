from __future__ import annotations

import json

from langchain_core.tools import tool

from app.db.connection_manager import connection_manager
from app.db.query_runner import QueryRunner


@tool
async def execute_sql(sql: str, connection_id: str) -> str:
    """Execute a SQL SELECT query against the connected database.

    Works with both PostgreSQL and Cosmos DB connections automatically.

    Args:
        sql: The SQL SELECT query to execute.
        connection_id: The database connection identifier.

    Returns:
        JSON string with keys: columns, data, row_count, duration_ms, error.
    """
    # ── Guardrail Layer 3: SQL validation ─────────────────────────
    from app.guardrails.sql_validator import validate_sql, Verdict
    conn_type = connection_manager.get_connection_type(connection_id)
    validator_result = validate_sql(sql, conn_type or "postgresql")

    if validator_result.verdict == Verdict.BLOCK:
        return json.dumps({
            "error": f"Query blocked by security policy: {validator_result.reason}",
            "data": [], "columns": [], "row_count": 0, "duration_ms": 0,
            "guardrail_blocked": True,
        })

    if validator_result.verdict == Verdict.FLAG:
        import logging
        logging.getLogger("guardrails.sql").warning(
            "FLAGGED SQL: %s | reason=%s", sql[:200], validator_result.reason,
        )

    if conn_type is None:
        return json.dumps({
            "error": f"Connection {connection_id} not found",
            "data": [], "columns": [], "row_count": 0, "duration_ms": 0,
        })

    if conn_type == "cosmosdb":
        from app.db.cosmos_manager import cosmos_manager
        result = cosmos_manager.execute_query(connection_id, sql)
        return json.dumps(result, default=str)

    if conn_type == "powerbi":
        from app.db.powerbi_manager import powerbi_manager
        result = powerbi_manager.execute_query(connection_id, sql)
        return json.dumps(result, default=str)

    # PostgreSQL / SQL databases
    engine = connection_manager.get_engine(connection_id)
    if engine is None:
        return json.dumps({
            "error": f"Connection engine {connection_id} not found",
            "data": [], "columns": [], "row_count": 0, "duration_ms": 0,
        })

    result = await QueryRunner.execute(engine, sql)
    return json.dumps(result, default=str)
