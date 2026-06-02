"""Scope API — returns customer list for the workspace scope selector."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.api.routes.users import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/scope/customers")
async def list_customers(
    connection_id: str = Query(..., description="Database connection ID"),
    table: str = Query("invoice", description="Table that contains customer columns"),
    id_col: str = Query("customer_id", description="Customer ID column"),
    name_col: str = Query("customer_name", description="Customer name column"),
    code_col: str = Query("customer_code", description="Customer code column"),
    current_user: dict = Depends(get_current_user),
):
    """Return distinct customers from the configured table.

    Privileged users (admin / manager) see the full list — they use the
    dropdown to switch scopes. Non-privileged users with a bound
    ``customer_code`` only see their own customer (single-row list), so the
    dropdown — when shown — cannot enumerate or leak other customers.
    Defaults to SELECT DISTINCT customer_id, customer_code, customer_name FROM invoice.
    Always returns {customers: []} on error — never crashes the UI.
    """
    from app.db.connection_manager import connection_manager

    conn_type = connection_manager.get_connection_type(connection_id)
    if conn_type is None:
        return {"customers": [], "error": f"Connection {connection_id} not found"}

    try:
        if conn_type == "cosmosdb":
            customers = _fetch_customers_cosmos(connection_id, table, id_col, name_col, code_col)
        elif conn_type == "powerbi":
            return {"customers": [], "error": "Not supported for Power BI"}
        else:
            customers = await _fetch_customers_sql(connection_id, table, id_col, name_col, code_col)
    except Exception as exc:
        logger.warning("scope/customers fetch failed (conn=%s): %s", connection_id, exc)
        return {"customers": [], "error": str(exc)}

    # Server-side filter: a scoped user can only see their own customer.
    # Admins/managers see everything (their dropdown is the source of truth).
    role = current_user.get("role", "user")
    bound_code = (current_user.get("customer_code") or "").strip()
    if role not in ("admin", "manager", "moderator") and bound_code:
        customers = [c for c in customers if str(c.get("code", "")).strip() == bound_code]

    return {"customers": customers}


# ── Row fetchers ──────────────────────────────────────────────────────

async def _fetch_customers_sql(
    connection_id: str,
    table: str,
    id_col: str,
    name_col: str,
    code_col: str,
) -> list[dict]:
    from app.db.connection_manager import connection_manager
    from sqlalchemy import text

    engine = connection_manager.get_engine(connection_id)
    if engine is None:
        raise ValueError(f"No SQL engine for connection {connection_id}")

    async with engine.connect() as conn:
        # Discover which of the requested columns actually exist
        col_rows = (await conn.execute(
            text(
                "SELECT LOWER(column_name) FROM information_schema.columns "
                "WHERE LOWER(table_name) = LOWER(:tbl)"
            ),
            {"tbl": table},
        )).fetchall()
        existing = {r[0] for r in col_rows}

    has_id   = id_col.lower() in existing
    has_name = name_col.lower() in existing
    has_code = code_col.lower() in existing

    if not has_id and not has_name:
        raise ValueError(f"Neither {id_col!r} nor {name_col!r} found in table {table!r} (columns: {existing})")

    select_parts = []
    if has_id:   select_parts.append(id_col)
    if has_code: select_parts.append(code_col)
    if has_name: select_parts.append(name_col)

    # Group by id to deduplicate — take the first name/code per customer_id
    group_col = id_col if has_id else (name_col if has_name else code_col)
    name_expr = f"MIN({name_col})" if has_name else "''"
    code_expr = f"MIN({code_col})" if has_code else "''"
    id_expr   = id_col if has_id else "''"
    order_col = f"MIN({name_col})" if has_name else id_col

    if has_id:
        sql = (
            f"SELECT {id_expr}, {code_expr}, {name_expr} "
            f"FROM {table} "
            f"GROUP BY {group_col} "
            f"ORDER BY {order_col}"
        )
    else:
        sql = (
            f"SELECT DISTINCT {', '.join(select_parts)} "
            f"FROM {table} "
            f"ORDER BY {order_col}"
        )

    async with engine.connect() as conn:
        rows = (await conn.execute(text(sql))).fetchall()

    result = []
    for row in rows:
        rid   = str(row[0]) if row[0] is not None else ""
        rcode = str(row[1]) if row[1] is not None else ""
        rname = str(row[2]) if row[2] is not None else ""
        if rid or rname:
            result.append({"id": rid, "code": rcode, "name": rname})
    return result


def _fetch_customers_cosmos(
    connection_id: str,
    table: str,
    id_col: str,
    name_col: str,
    code_col: str,
) -> list[dict]:
    from app.db.cosmos_manager import cosmos_manager

    # Cosmos DB does not support SELECT DISTINCT — fetch all and deduplicate in Python.
    sql = (
        f"SELECT c.{id_col}, c.{code_col}, c.{name_col} "
        f"FROM {table} c ORDER BY c.{name_col}"
    )
    result = cosmos_manager.execute_query(connection_id, sql)

    seen: set[str] = set()
    customers: list[dict] = []
    for row in result.get("data", []):
        uid = str(row.get(id_col, ""))
        if not uid or uid in seen:
            continue
        seen.add(uid)
        customers.append({
            "id":   uid,
            "code": str(row.get(code_col, "")),
            "name": str(row.get(name_col, "")),
        })
    return customers
