from __future__ import annotations

import contextvars
import hashlib
import json
import re
import time

from langchain_core.tools import tool

from app.db.connection_manager import connection_manager
from app.db.query_runner import QueryRunner
from app.utils.ttl_cache import TTLCache


_sql_result_cache: TTLCache[dict] = TTLCache(ttl_seconds=15, max_size=128)

# Set by graph.py before each agent run so the tool can enforce customer
# scope without the LLM needing to receive it as an argument.
_customer_scope_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "customer_scope", default=""
)

# Tables that carry customer-level data and MUST be filtered by customer_id
# whenever a customer-scoped user is making a query.
_CUSTOMER_SENSITIVE_TABLES = re.compile(
    r"\b(invoice|customer_master)\b", re.IGNORECASE
)
# Matches customer_id filtered against a LITERAL value (string or number).
# Must NOT match JOIN conditions like "b.customer_id = cm.customer_id" —
# those have another identifier after =, not a quote or digit.
_CUSTOMER_ID_FILTER = re.compile(
    r"\bcustomer_id\s*(?:=\s*(?:['\"]|\d)|IN\s*\()",
    re.IGNORECASE,
)
_NONDETERMINISTIC_SQL_MARKERS = (
    "CURRENT_TIMESTAMP",
    "CURRENT_DATE",
    "CURRENT_TIME",
    "NOW(",
    "RANDOM(",
    "UUID(",
)


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

    # ── Customer scope guard (hard enforcement) ───────────────────
    # The LLM is instructed via the system prompt to always filter by
    # customer_id for scoped users. This is the code-level backstop: if
    # the generated SQL touches customer-sensitive tables but omits the
    # filter, the query is blocked and the LLM is told to retry with it.
    scope = _customer_scope_ctx.get()
    if scope:
        touches_sensitive = bool(_CUSTOMER_SENSITIVE_TABLES.search(sql))
        has_filter = bool(_CUSTOMER_ID_FILTER.search(sql))
        if touches_sensitive and not has_filter:
            import logging
            logging.getLogger("guardrails.scope").warning(
                "SCOPE VIOLATION blocked | scope=%s | sql=%s", scope, sql[:300],
            )
            return json.dumps({
                "error": (
                    f"Scope violation: this query accesses customer data tables "
                    f"(invoice / customer_master) without filtering by customer_id. "
                    f"You MUST add 'WHERE customer_id = ''{scope}''' "
                    f"(or an equivalent CTE/subquery filter) and retry."
                ),
                "data": [], "columns": [], "row_count": 0, "duration_ms": 0,
                "scope_blocked": True,
            })

    if conn_type is None:
        return json.dumps({
            "error": f"Connection {connection_id} not found",
            "data": [], "columns": [], "row_count": 0, "duration_ms": 0,
        })

    cache_key = _build_sql_cache_key(connection_id, conn_type, sql)
    cache_start = time.perf_counter()
    if cache_key:
        cached_result = _sql_result_cache.get(cache_key)
        if cached_result is not None:
            cached_result["cached"] = True
            cached_result["duration_ms"] = round((time.perf_counter() - cache_start) * 1000, 2)
            return json.dumps(cached_result, default=str)

    if conn_type == "cosmosdb":
        from app.db.cosmos_manager import cosmos_manager
        result = cosmos_manager.execute_query(connection_id, sql)
        _cache_sql_result(cache_key, result)
        return json.dumps(result, default=str)

    if conn_type == "powerbi":
        from app.db.powerbi_manager import powerbi_manager
        result = powerbi_manager.execute_query(connection_id, sql)
        _cache_sql_result(cache_key, result)
        return json.dumps(result, default=str)

    # PostgreSQL / SQL databases
    engine = connection_manager.get_engine(connection_id)
    if engine is None:
        return json.dumps({
            "error": f"Connection engine {connection_id} not found",
            "data": [], "columns": [], "row_count": 0, "duration_ms": 0,
        })

    result = await QueryRunner.execute(engine, sql)
    _cache_sql_result(cache_key, result)
    return json.dumps(result, default=str)


def _build_sql_cache_key(connection_id: str, conn_type: str, sql: str) -> str | None:
    normalized_sql = sql.strip()
    upper_sql = normalized_sql.upper()
    if any(marker in upper_sql for marker in _NONDETERMINISTIC_SQL_MARKERS):
        return None
    digest = hashlib.sha256(f"{connection_id}:{conn_type}:{normalized_sql}".encode()).hexdigest()
    return digest[:32]


def _cache_sql_result(cache_key: str | None, result: dict) -> None:
    if cache_key is None:
        return
    if result.get("error"):
        return
    if result.get("row_count", 0) > 1000:
        return
    _sql_result_cache.set(cache_key, result)
