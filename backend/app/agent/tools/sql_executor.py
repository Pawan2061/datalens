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
# The column the scope value pins against. Locked users are bound by
# customer_code; the privileged "Viewing as" dropdown passes a customer_id.
# Either way the guard also accepts the other customer column for safety —
# both identify exactly one customer.
_customer_scope_field_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "customer_scope_field", default="customer_id"
)

# Tables that carry customer-level data and MUST be filtered to the scoped
# customer whenever a customer-scoped user is making a query.
_CUSTOMER_SENSITIVE_TABLES = re.compile(
    r"\b(invoice|customer_master)\b", re.IGNORECASE
)

# Constructs that BROADEN a customer filter beyond a single pinned value.
# These are the classic ways a query "looks filtered" yet still returns other
# customers' rows, so in scoped mode they are blocked outright:
#   customer_id != X / <> X         → everyone except one
#   customer_id NOT IN (...)        → everyone except a few
#   customer_id IN (SELECT ...)     → a whole subquery's worth of customers
_SCOPE_BROADENING = re.compile(
    r"customer_(?:id|code)\s*(?:!=|<>)"
    r"|customer_(?:id|code)\s+NOT\s+IN"
    r"|customer_(?:id|code)\s+IN\s*\(\s*SELECT",
    re.IGNORECASE,
)

# Any customer_id / customer_code equated to a STRING or NUMERIC literal.
# Used to verify every such literal equals the scoped value — catches
# "customer_id = 'A' OR customer_id = 'B'" style broadening.
_CUSTOMER_ID_LITERAL_EQ = re.compile(
    r"customer_(?:id|code)\s*=\s*(?:'([^']*)'|(\d+))",
    re.IGNORECASE,
)


def _scope_pin_ok(sql: str, scope: str) -> bool:
    """True iff `sql` pins a customer column to EXACTLY the scoped value.

    Accepts `customer_id`/`customer_code = '<scope>'`, the unquoted numeric
    form, or a single-value `IN ('<scope>')`. The value must equal the scope
    exactly — a pin to any other customer does not count.
    """
    esc = re.escape(scope)
    pinned = re.compile(
        rf"customer_(?:id|code)\s*=\s*'{esc}'"
        rf"|customer_(?:id|code)\s*=\s*{esc}(?![\w])"
        rf"|customer_(?:id|code)\s+IN\s*\(\s*'{esc}'\s*\)"
        rf"|customer_(?:id|code)\s+IN\s*\(\s*{esc}\s*\)",
        re.IGNORECASE,
    )
    return bool(pinned.search(sql))


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
    # The LLM is instructed via the system prompt to pin every customer-table
    # query to the scoped customer. This is the code-level backstop and the
    # real security boundary: any query touching invoice / customer_master in
    # scoped mode is BLOCKED unless it pins a customer column to EXACTLY the
    # scoped value and contains no broadening construct. A regex "a filter
    # exists" check is NOT enough — `customer_id IN (SELECT ...)` or a filter
    # on city/state would otherwise leak every other customer's rows.
    scope = _customer_scope_ctx.get()
    if scope and _CUSTOMER_SENSITIVE_TABLES.search(sql):
        field = _customer_scope_field_ctx.get() or "customer_id"

        # (a) Reject constructs that broaden past a single pinned customer.
        broadened = bool(_SCOPE_BROADENING.search(sql))

        # (b) Every customer_id/code equality literal must equal the scope —
        #     blocks "customer_id = 'X' OR customer_id = 'other'".
        other_customer = any(
            (m.group(1) if m.group(1) is not None else m.group(2)) != scope
            for m in _CUSTOMER_ID_LITERAL_EQ.finditer(sql)
        )

        # (c) There must be at least one exact pin to the scoped value.
        pinned = _scope_pin_ok(sql, scope)

        if broadened or other_customer or not pinned:
            import logging
            logging.getLogger("guardrails.scope").warning(
                "SCOPE VIOLATION blocked | scope=%s field=%s "
                "pinned=%s broadened=%s other_customer=%s | sql=%s",
                scope, field, pinned, broadened, other_customer, sql[:300],
            )
            return json.dumps({
                "error": (
                    f"Scope violation: in customer-scoped mode every query that "
                    f"touches invoice / customer_master must restrict results to "
                    f"the single scoped customer and nothing else. Rewrite the "
                    f"query so it includes 'WHERE {field} = ''{scope}''' "
                    f"(or the same filter inside each CTE/subquery), remove any "
                    f"customer_id/customer_code IN (subquery), != , <> or NOT IN, "
                    f"and do not reference any other customer's id, code, name, "
                    f"city or state. Retry with that filter."
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
