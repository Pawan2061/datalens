"""Workspace Intelligence Profiler.

Generates a rich narrative DATA INTELLIGENCE BRIEFING for a database connection:
1. Inspecting schema (tables, columns, types)
2. Sampling data (TOP rows, row counts)
3. Profiling columns (distinct values, min/max/avg, null rates)
4. Detecting data nuances (array columns, nested fields, special types)
5. LLM synthesis of a professional intelligence briefing with:
   — Executive summary of the data landscape
   — Data architecture & relationship narrative
   — Per-table intelligence assessments
   — Query strategy guide with data caveats
   — Intelligence playbook: 8-12 analysis directions with full narrative approaches
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.agent.models import AgentEvent, AgentEventType
from app.db.connection_manager import connection_manager
from app.schemas.profile import (
    ColumnProfile,
    DataProfile,
    DataProfileDoc,
    DirectionalQuestion,
    TableProfile,
)

logger = logging.getLogger(__name__)

# Maximum tables to profile (avoid huge schemas)
MAX_TABLES = 20
# Maximum distinct values to capture per column
MAX_DISTINCT = 20
# Sample rows per table
SAMPLE_ROWS = 5

_CONNECTOR_LABELS = {
    "cosmosdb": "Azure Cosmos DB",
    "powerbi": "Power BI",
    "mysql": "MySQL",
    "sqlserver": "SQL Server",
}


def _connector_label(conn_type: str) -> str:
    return _CONNECTOR_LABELS.get(conn_type, "PostgreSQL")


# ── Query execution helpers ──────────────────────────────────────

async def _run_query(connection_id: str, sql: str) -> dict:
    """Execute a SQL/DAX query and return the result dict."""
    conn_type = connection_manager.get_connection_type(connection_id)

    if conn_type == "cosmosdb":
        from app.db.cosmos_manager import cosmos_manager
        return cosmos_manager.execute_query(connection_id, sql)

    if conn_type == "powerbi":
        from app.db.powerbi_manager import powerbi_manager
        return powerbi_manager.execute_query(connection_id, sql)

    engine = connection_manager.get_engine(connection_id)
    if engine is None:
        return {"data": [], "columns": [], "row_count": 0, "error": "No engine"}

    from app.db.query_runner import QueryRunner
    return await QueryRunner.execute(engine, sql)


def _get_conn_type(connection_id: str) -> str:
    return connection_manager.get_connection_type(connection_id) or "postgresql"


# ── Step 1: Discover schema ─────────────────────────────────────

async def _discover_schema(connection_id: str) -> list[dict]:
    """Get table/container names and columns from the schema inspector."""
    conn_type = _get_conn_type(connection_id)

    if conn_type == "cosmosdb":
        from app.db.cosmos_manager import cosmos_manager
        schema_info = cosmos_manager.inspect_schema(connection_id)
    elif conn_type == "powerbi":
        from app.db.powerbi_manager import powerbi_manager
        schema_info = powerbi_manager.inspect_schema(connection_id)
    else:
        from app.db.schema_inspector import inspect_schema
        engine = connection_manager.get_engine(connection_id)
        schema_info = await inspect_schema(engine)

    tables = []
    for t in schema_info.tables[:MAX_TABLES]:
        tables.append({
            "name": t.name,
            "columns": [
                {"name": c.name, "type": c.type, "is_pk": c.is_primary_key}
                for c in t.columns
            ],
        })
    return tables


# ── Step 2: Sample and profile tables ────────────────────────────

async def _profile_table(
    connection_id: str,
    table: dict,
    conn_type: str,
) -> TableProfile:
    """Profile a single table: row count, samples, column stats."""
    tname = table["name"]
    columns = table["columns"]
    is_cosmos = conn_type == "cosmosdb"
    is_pbi = conn_type == "powerbi"

    # --- Row count ---
    if is_cosmos:
        count_sql = f"SELECT VALUE COUNT(1) FROM {tname}"
    elif is_pbi:
        count_sql = f'EVALUATE ROW("cnt", COUNTROWS(\'{tname}\'))'
    else:
        count_sql = f"SELECT COUNT(1) as cnt FROM {tname}"

    count_result = await _run_query(connection_id, count_sql)
    row_count = 0
    if count_result.get("data"):
        first_row = count_result["data"][0]
        if isinstance(first_row, dict):
            row_count = int(list(first_row.values())[0] or 0) if first_row else 0
        elif isinstance(first_row, (int, float)):
            row_count = int(first_row)

    # --- Sample rows ---
    if is_cosmos:
        sample_sql = f"SELECT TOP {SAMPLE_ROWS} * FROM {tname}"
    elif is_pbi:
        sample_sql = f"EVALUATE TOPN({SAMPLE_ROWS}, '{tname}')"
    else:
        sample_sql = f"SELECT * FROM {tname} LIMIT {SAMPLE_ROWS}"

    sample_result = await _run_query(connection_id, sample_sql)
    sample_rows = sample_result.get("data", [])[:SAMPLE_ROWS]

    # --- Column profiling ---
    col_profiles: list[ColumnProfile] = []

    # Classify columns
    numeric_cols = []
    categorical_cols = []
    for col in columns:
        cname = col["name"]
        ctype = col["type"].lower()
        if cname.startswith("_") and is_cosmos:
            col_profiles.append(ColumnProfile(name=cname, type=col["type"]))
            continue
        is_numeric = any(
            t in ctype
            for t in ("int", "float", "number", "numeric", "decimal", "double", "real", "money", "currency")
        )
        if is_numeric:
            numeric_cols.append(col)
        else:
            categorical_cols.append(col)

    # ── FAST PATH: PostgreSQL — batch all stats in 1-2 queries ───
    if not is_cosmos and not is_pbi:
        col_stats: dict[str, dict] = {}  # cname -> {min_val, max_val, avg_val, null_pct, ...}

        # Batch numeric stats + null counts in ONE query
        if numeric_cols or categorical_cols:
            parts = []
            for col in numeric_cols:
                cn = col["name"]
                parts.append(f'MIN("{cn}") AS "{cn}__min"')
                parts.append(f'MAX("{cn}") AS "{cn}__max"')
                parts.append(f'AVG("{cn}"::numeric) AS "{cn}__avg"')
                parts.append(f'SUM(CASE WHEN "{cn}" IS NULL THEN 1 ELSE 0 END) AS "{cn}__null"')
            for col in categorical_cols:
                cn = col["name"]
                parts.append(f'COUNT(DISTINCT "{cn}") AS "{cn}__dist"')
                parts.append(f'SUM(CASE WHEN "{cn}" IS NULL THEN 1 ELSE 0 END) AS "{cn}__null"')

            if parts:
                batch_sql = f"SELECT {', '.join(parts)} FROM {tname}"
                try:
                    batch_r = await _run_query(connection_id, batch_sql)
                    if batch_r.get("data"):
                        row = batch_r["data"][0]
                        for col in numeric_cols:
                            cn = col["name"]
                            col_stats[cn] = {
                                "min_val": _to_float(row.get(f"{cn}__min")),
                                "max_val": _to_float(row.get(f"{cn}__max")),
                                "avg_val": round(_to_float(row.get(f"{cn}__avg")) or 0, 2) if row.get(f"{cn}__avg") is not None else None,
                                "null_count": int(row.get(f"{cn}__null") or 0),
                            }
                        for col in categorical_cols:
                            cn = col["name"]
                            col_stats[cn] = {
                                "distinct_count": int(row.get(f"{cn}__dist") or 0),
                                "null_count": int(row.get(f"{cn}__null") or 0),
                            }
                except Exception as e:
                    logger.warning("Batch stats query failed for %s: %s", tname, e)

        # Build column profiles from batch results
        for col in numeric_cols:
            cn = col["name"]
            profile = ColumnProfile(name=cn, type=col["type"])
            stats = col_stats.get(cn, {})
            profile.min_val = stats.get("min_val")
            profile.max_val = stats.get("max_val")
            profile.avg_val = stats.get("avg_val")
            if row_count > 0 and stats.get("null_count"):
                profile.null_pct = round(stats["null_count"] / row_count * 100, 1)
            col_profiles.append(profile)

        # Categorical: get top values via concurrent queries (max 5 at a time)
        async def _get_top_values(col: dict) -> ColumnProfile:
            cn = col["name"]
            profile = ColumnProfile(name=cn, type=col["type"])
            stats = col_stats.get(cn, {})
            profile.distinct_count = stats.get("distinct_count")
            if row_count > 0 and stats.get("null_count"):
                profile.null_pct = round(stats["null_count"] / row_count * 100, 1)
            try:
                dist_sql = (
                    f'SELECT "{cn}" as val, COUNT(1) as cnt '
                    f"FROM {tname} "
                    f'GROUP BY "{cn}" '
                    f"ORDER BY cnt DESC "
                    f"LIMIT {MAX_DISTINCT}"
                )
                dist_r = await _run_query(connection_id, dist_sql)
                if dist_r.get("data"):
                    total = row_count or 1
                    top_values = []
                    for drow in dist_r["data"][:10]:
                        val = drow.get("val") or drow.get(cn, "")
                        cnt = drow.get("cnt")
                        if cnt and total > 0:
                            pct = round(int(cnt) / total * 100, 1)
                            top_values.append(f"{val} ({pct}%)")
                        else:
                            top_values.append(str(val))
                    profile.top_values = top_values
            except Exception as e:
                logger.warning("Top values query failed for %s.%s: %s", tname, cn, e)
            return profile

        # Run categorical top-values queries concurrently (batches of 5)
        for i in range(0, len(categorical_cols), 5):
            batch = categorical_cols[i:i + 5]
            results = await asyncio.gather(*[_get_top_values(c) for c in batch])
            col_profiles.extend(results)

    else:
        # ── SLOW PATH: Cosmos DB / Power BI — column-by-column ───
        for col in (numeric_cols + categorical_cols):
            cname = col["name"]
            ctype = col["type"].lower()
            profile = ColumnProfile(name=cname, type=col["type"])
            is_numeric = col in numeric_cols

            try:
                if is_numeric:
                    if is_cosmos:
                        min_r = await _run_query(connection_id, f"SELECT VALUE MIN(c.{cname}) FROM {tname} c")
                        max_r = await _run_query(connection_id, f"SELECT VALUE MAX(c.{cname}) FROM {tname} c")
                        avg_r = await _run_query(connection_id, f"SELECT VALUE AVG(c.{cname}) FROM {tname} c")
                        if min_r.get("data"):
                            v = min_r["data"][0]
                            profile.min_val = float(v) if isinstance(v, (int, float)) else None
                        if max_r.get("data"):
                            v = max_r["data"][0]
                            profile.max_val = float(v) if isinstance(v, (int, float)) else None
                        if avg_r.get("data"):
                            v = avg_r["data"][0]
                            profile.avg_val = round(float(v), 2) if isinstance(v, (int, float)) else None
                    elif is_pbi:
                        stat_dax = (
                            f'EVALUATE ROW('
                            f'"min_val", MIN(\'{tname}\'[{cname}]), '
                            f'"max_val", MAX(\'{tname}\'[{cname}]), '
                            f'"avg_val", AVERAGE(\'{tname}\'[{cname}]))'
                        )
                        stat_r = await _run_query(connection_id, stat_dax)
                        if stat_r.get("data"):
                            row = stat_r["data"][0]
                            profile.min_val = _to_float(row.get("min_val"))
                            profile.max_val = _to_float(row.get("max_val"))
                            profile.avg_val = round(_to_float(row.get("avg_val")) or 0, 2) if row.get("avg_val") is not None else None
                else:
                    if is_cosmos:
                        dist_sql = (
                            f"SELECT TOP {MAX_DISTINCT} c.{cname} as val "
                            f"FROM {tname} c "
                            f"GROUP BY c.{cname}"
                        )
                    elif is_pbi:
                        dist_sql = (
                            f"EVALUATE TOPN({MAX_DISTINCT}, "
                            f"SUMMARIZECOLUMNS('{tname}'[{cname}], "
                            f"\"cnt\", COUNTROWS('{tname}')), "
                            f"[cnt], DESC)"
                        )
                    else:
                        dist_sql = ""
                    if dist_sql:
                        dist_r = await _run_query(connection_id, dist_sql)
                        if dist_r.get("data"):
                            total = row_count or 1
                            top_values = []
                            for drow in dist_r["data"][:10]:
                                val = drow.get("val") or drow.get(cname, "")
                                cnt = drow.get("cnt")
                                if cnt and total > 0:
                                    pct = round(int(cnt) / total * 100, 1)
                                    top_values.append(f"{val} ({pct}%)")
                                else:
                                    top_values.append(str(val))
                            profile.top_values = top_values
                            profile.distinct_count = len(dist_r["data"])

                # Null percentage
                if row_count > 0:
                    if is_cosmos:
                        null_sql = (
                            f"SELECT VALUE COUNT(1) FROM {tname} c "
                            f"WHERE NOT IS_DEFINED(c.{cname}) OR IS_NULL(c.{cname})"
                        )
                    elif is_pbi:
                        null_sql = (
                            f'EVALUATE ROW("cnt", COUNTBLANK(\'{tname}\'[{cname}]))'
                        )
                    else:
                        null_sql = ""
                    if null_sql:
                        null_r = await _run_query(connection_id, null_sql)
                        if null_r.get("data"):
                            null_val = null_r["data"][0]
                            if isinstance(null_val, dict):
                                null_count = int(list(null_val.values())[0] or 0)
                            elif isinstance(null_val, (int, float)):
                                null_count = int(null_val)
                            else:
                                null_count = 0
                            profile.null_pct = round(null_count / row_count * 100, 1)

            except Exception as e:
                logger.warning("Failed to profile column %s.%s: %s", tname, cname, e)

            col_profiles.append(profile)

    # --- Expand nested object sub-fields ---
    # Detect nested objects from sample data and profile their sub-fields
    # so the agent knows exactly what's inside them and can query directly.
    if sample_rows and is_cosmos:
        nested_profiles = await _expand_nested_fields(
            connection_id, tname, sample_rows, col_profiles,
        )
        col_profiles.extend(nested_profiles)

    return TableProfile(
        name=tname,
        row_count=row_count,
        columns=col_profiles,
        sample_rows=sample_rows[:3],  # Keep 3 for the stored profile
    )


async def _expand_nested_fields(
    connection_id: str,
    table_name: str,
    sample_rows: list[dict],
    existing_columns: list[ColumnProfile],
) -> list[ColumnProfile]:
    """Discover and profile sub-fields inside nested objects.

    For Cosmos DB, nested objects like field_level_accuracy = {company_code: 95.5, ...}
    are common. This function:
    1. Detects nested object columns from sample data
    2. Enumerates ALL sub-field keys
    3. Profiles numeric sub-fields (min/max/avg)
    4. Returns ColumnProfile entries named "parent.subfield" so the agent can query them.
    """
    existing_names = {c.name for c in existing_columns}
    nested_profiles: list[ColumnProfile] = []

    for col in existing_columns:
        if col.name.startswith("_"):
            continue
        # Check if this column is a nested object in sample data
        sample_val = None
        for row in sample_rows[:3]:
            val = row.get(col.name)
            if isinstance(val, dict):
                sample_val = val
                break
        if sample_val is None:
            continue

        # Collect ALL unique keys across sample rows
        all_keys: dict[str, str] = {}  # key -> detected type
        for row in sample_rows:
            val = row.get(col.name)
            if not isinstance(val, dict):
                continue
            for k, v in val.items():
                if k not in all_keys:
                    if isinstance(v, (int, float)):
                        all_keys[k] = "number"
                    elif isinstance(v, str):
                        all_keys[k] = "string"
                    elif isinstance(v, bool):
                        all_keys[k] = "boolean"
                    else:
                        all_keys[k] = "unknown"

        # Profile each sub-field
        for subkey, subtype in all_keys.items():
            full_name = f"{col.name}.{subkey}"
            if full_name in existing_names:
                continue

            profile = ColumnProfile(
                name=full_name,
                type=f"nested_{subtype}",
            )

            if subtype == "number":
                try:
                    # Query min/max/avg for this nested numeric field
                    min_r = await _run_query(
                        connection_id,
                        f"SELECT VALUE MIN(c.{full_name}) FROM {table_name} c",
                    )
                    max_r = await _run_query(
                        connection_id,
                        f"SELECT VALUE MAX(c.{full_name}) FROM {table_name} c",
                    )
                    avg_r = await _run_query(
                        connection_id,
                        f"SELECT VALUE AVG(c.{full_name}) FROM {table_name} c",
                    )
                    if min_r.get("data"):
                        v = min_r["data"][0]
                        profile.min_val = float(v) if isinstance(v, (int, float)) else None
                    if max_r.get("data"):
                        v = max_r["data"][0]
                        profile.max_val = float(v) if isinstance(v, (int, float)) else None
                    if avg_r.get("data"):
                        v = avg_r["data"][0]
                        profile.avg_val = round(float(v), 2) if isinstance(v, (int, float)) else None
                except Exception as e:
                    logger.warning("Failed to profile nested field %s.%s: %s", table_name, full_name, e)
            elif subtype == "string":
                # Get sample values for string sub-fields
                try:
                    dist_sql = (
                        f"SELECT TOP 10 c.{full_name} as val "
                        f"FROM {table_name} c "
                        f"GROUP BY c.{full_name}"
                    )
                    dist_r = await _run_query(connection_id, dist_sql)
                    if dist_r.get("data"):
                        profile.top_values = [
                            str(row.get("val", ""))
                            for row in dist_r["data"][:8]
                        ]
                        profile.distinct_count = len(dist_r["data"])
                except Exception:
                    pass

            nested_profiles.append(profile)

    return nested_profiles


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ── Step 3: Detect data nuances per table ────────────────────────

def _detect_query_guidance(
    table: TableProfile,
    conn_type: str,
    sample_rows: list[dict],
) -> list[str]:
    """Detect data nuances and generate query guidance for a table.

    Checks for: array columns, nested objects, date columns, special types.
    """
    guidance: list[str] = []
    is_cosmos = conn_type == "cosmosdb"

    for col in table.columns:
        if col.name.startswith("_"):
            continue
        ctype = col.type.lower()

        # Detect array columns from type or sample data
        is_array = "array" in ctype or "list" in ctype
        if not is_array and sample_rows:
            for row in sample_rows[:2]:
                val = row.get(col.name)
                if isinstance(val, list):
                    is_array = True
                    break

        if is_array:
            if is_cosmos:
                guidance.append(
                    f"ARRAY: '{col.name}' is an array field. "
                    f"NEVER use SELECT DISTINCT or GROUP BY on it. "
                    f"Use ARRAY_LENGTH(c.{col.name}) to count items, "
                    f"ARRAY_CONTAINS(c.{col.name}, 'value') to check membership, "
                    f"or SELECT TOP 50 c.{col.name} FROM ... to retrieve raw values."
                )
            else:
                guidance.append(
                    f"ARRAY: '{col.name}' is an array/list column — "
                    f"may need unnesting or special handling."
                )

        # Detect nested objects
        is_object = "object" in ctype
        if not is_object and sample_rows:
            for row in sample_rows[:2]:
                val = row.get(col.name)
                if isinstance(val, dict):
                    is_object = True
                    all_keys = list(val.keys())
                    numeric_keys = [
                        k for k, v in val.items()
                        if isinstance(v, (int, float))
                    ]
                    string_keys = [
                        k for k, v in val.items()
                        if isinstance(v, str)
                    ]
                    guidance.append(
                        f"NESTED OBJECT: '{col.name}' contains {len(all_keys)} sub-fields: "
                        f"{', '.join(all_keys)}. "
                        f"Access each sub-field with dot notation: c.{col.name}.{all_keys[0]}. "
                    )
                    if numeric_keys:
                        example_key = numeric_keys[0]
                        guidance.append(
                            f"  → NUMERIC sub-fields in '{col.name}': {', '.join(numeric_keys)}. "
                            f"Query them directly: AVG(c.{col.name}.{example_key}), "
                            f"MIN(c.{col.name}.{example_key}), MAX(c.{col.name}.{example_key}). "
                            f"To COMPARE all sub-fields, query each one: "
                            f"SELECT {', '.join(f'AVG(c.{col.name}.{k}) as avg_{k}' for k in numeric_keys[:6])} "
                            f"FROM {table.name} c"
                        )
                    if string_keys:
                        guidance.append(
                            f"  → STRING sub-fields in '{col.name}': {', '.join(string_keys)}."
                        )
                    break

        # High null percentage warning
        if col.null_pct > 30:
            guidance.append(
                f"HIGH NULL: '{col.name}' has {col.null_pct}% null values — "
                f"always filter with IS_DEFINED or IS NOT NULL before aggregating."
            )

    return guidance


# ── Step 4: LLM directional synthesis ────────────────────────────

_INTELLIGENCE_BRIEFING_BASE = """\
You are a senior data analyst. Given database schema, statistics, and sample data,
create an ANALYSIS PLAN — a compact reference an AI agent will use to answer user
questions about this data.

Output a JSON object with these sections:

1. "executive_summary": 2-3 sentences. What business domain is this? What are the
   key entities and scale? Keep it tight.

2. "data_architecture": 1-2 sentences. How do tables relate? Shared dimensions?
   Skip if tables are independent.

3. "kpis": List of 5-10 key performance indicators discoverable from this data.
   Each KPI is a short string like "Invoice processing accuracy rate",
   "Monthly invoice volume by tenant", "Average processing time per document type".
   Focus on metrics a business user would track.

4. "tables": For each business table (skip internal tables like chat_*, email_*, etc.):
   - "name": exact table name
   - "narrative": 1-2 sentences — what this table tracks, notable patterns.
   - "analysis_angles": 2-3 specific questions this table answers

5. "intelligence_playbook": 8-12 analysis directions covering the KPIs. For EACH:
   - "title": Short title (e.g. "Invoice Volume by Month")
   - "question": Natural language question a user might ask
   - "narrative": 2-3 sentences: what to query, which columns, caveats.
   - "query_template": CONCRETE, EXECUTABLE query using REAL table/column names.
     This is the most important field — must be copy-paste ready.
   - "tables": list of table names
   - "key_columns": list of columns

{engine_rules}

RULES:
- Use REAL column names from the schema. Queries must be executable as-is.
- Cover diverse angles: volumes, rates, trends, comparisons, top-N, distributions.
- Questions must be DIRECTLY answerable — no vague or subjective ones.
- Skip internal/system tables (chat_*, email_*, migration*, session*, etc.)
- If a column has high null %, mention filtering in the narrative.
- Keep narratives concise — this is a reference plan, not an essay.

Output ONLY valid JSON (no markdown fences, no commentary).
"""

_COSMOS_QUERY_RULES = """\
COSMOS DB QUERY TEMPLATE RULES (THIS IS COSMOS DB — FOLLOW STRICTLY):
- Every query MUST use: SELECT ... FROM container_name c — the alias 'c' is MANDATORY.
- EVERY field MUST be prefixed with c. — e.g. c.tenant, c.status, c.processing_time.
- Use COUNT(1) — NEVER COUNT(*).
- GROUP BY fields MUST also use c. prefix: GROUP BY c.tenant.
- ORDER BY uses c. prefix too: ORDER BY c.tenant.

ABSOLUTELY FORBIDDEN IN COSMOS DB (these will cause runtime errors):
- NO CASE WHEN / CASE expressions
- NO subqueries (no nested SELECT)
- NO JOINs between containers
- NO HAVING clause
- NO UNION
- NO window functions (no OVER, PARTITION BY, ROW_NUMBER, RANK)
- NO CTEs (no WITH clause)
- NO COUNT(*)

RATE/PERCENTAGE CALCULATIONS IN COSMOS DB:
Since CASE WHEN is not available, you CANNOT calculate rates in a single query.
For rate questions (e.g. "failure rate by tenant"), you need TWO queries:
  Query 1 (filtered): SELECT c.tenant, COUNT(1) as failed FROM bucket_report c WHERE c.validation_status = 'Failed' GROUP BY c.tenant
  Query 2 (total): SELECT c.tenant, COUNT(1) as total FROM bucket_report c GROUP BY c.tenant
The agent will combine the results to calculate the rate.
In the query_template field, provide the PRIMARY query (usually the filtered one).
In the narrative, ALWAYS explain that a second total-count query is needed for rate calculations.

ARRAY COLUMNS IN COSMOS DB:
- NEVER use GROUP BY or SELECT DISTINCT on array fields — it WILL error.
- Use ARRAY_LENGTH(c.field) to count items in the array.
- Use ARRAY_CONTAINS(c.field, 'value') to check membership.
- To analyze array contents: first SELECT TOP 50 c.field FROM container c WHERE ARRAY_LENGTH(c.field) > 0, \
  then use ARRAY_CONTAINS for each discovered value.

EXAMPLE COSMOS DB query_templates:
- Count by group: "SELECT c.tenant, COUNT(1) as cnt FROM bucket_report c GROUP BY c.tenant"
- Filtered count: "SELECT c.tenant, COUNT(1) as failed FROM bucket_report c WHERE c.validation_status = 'Failed' GROUP BY c.tenant"
- Aggregate stats: "SELECT c.tenant, COUNT(1) as total, AVG(c.processing_time) as avg_time, MIN(c.processing_time) as min_time, MAX(c.processing_time) as max_time FROM bucket_report c GROUP BY c.tenant"
- Top N: "SELECT TOP 10 c.tenant, c.status, c.processing_time FROM bucket_report c ORDER BY c.processing_time DESC"
- Array check: "SELECT c.id, c.tenant FROM bucket_report c WHERE ARRAY_CONTAINS(c.error_reason_list, 'Missing field')"
"""

_SQL_QUERY_RULES = """\
SQL QUERY TEMPLATE RULES (PostgreSQL / MySQL / SQL Server):
- Use standard SQL syntax. CASE WHEN, JOINs, subqueries, CTEs are all fine.
- For rate/percentage calculations, use CASE WHEN:
  SELECT tenant, COUNT(CASE WHEN validation_status = 'Failed' THEN 1 END)::float / COUNT(*) AS failed_rate
  FROM bucket_report GROUP BY tenant ORDER BY failed_rate DESC
- Use appropriate type casts: ::float for PostgreSQL, CAST(... AS FLOAT) for SQL Server/MySQL.
- ORDER BY the most relevant metric DESC so top results come first.
- For multiple metrics on the same dimension, combine into ONE query:
  SELECT tenant, COUNT(*) as total, AVG(processing_time) as avg_time,
  COUNT(CASE WHEN status = 'Failed' THEN 1 END) as failed_count
  FROM table_name GROUP BY tenant
"""

_DAX_QUERY_RULES = """\
POWER BI DAX QUERY TEMPLATE RULES:
- All queries MUST start with EVALUATE.
- Use SUMMARIZECOLUMNS for grouping/aggregating:
  EVALUATE SUMMARIZECOLUMNS(Sales[Region], "Total", SUM(Sales[Amount]))
- Column references use Table[Column] notation.
- Use CALCULATE + FILTER for conditional aggregation:
  EVALUATE SUMMARIZECOLUMNS(bucket_report[tenant],
    "Failed", CALCULATE(COUNTROWS(bucket_report), bucket_report[validation_status] = "Failed"),
    "Total", COUNTROWS(bucket_report))
- Use TOPN to limit: EVALUATE TOPN(10, table, column, DESC)
- NO SQL syntax (no SELECT, FROM, WHERE, GROUP BY, JOIN).
"""


def _get_engine_rules(conn_type: str) -> str:
    """Return engine-specific query rules for the intelligence briefing prompt."""
    if conn_type == "cosmosdb":
        return _COSMOS_QUERY_RULES
    if conn_type == "powerbi":
        return _DAX_QUERY_RULES
    return _SQL_QUERY_RULES


async def _synthesize_intelligence_briefing(
    table_profiles: list[TableProfile],
    connector_label: str,
    conn_type: str,
) -> dict:
    """Use LLM to generate a rich narrative intelligence briefing."""
    from langchain_core.messages import HumanMessage, SystemMessage
    from app.llm.openai_llm import get_worker_llm

    # Build engine-specific prompt
    engine_rules = _get_engine_rules(conn_type)
    system_prompt = _INTELLIGENCE_BRIEFING_BASE.format(engine_rules=engine_rules)

    # Build a compact data summary for the LLM — skip internal tables + garbage columns
    summary_parts = []
    for tp in table_profiles:
        # Skip internal/system tables from synthesis
        if _is_skip_table(tp.name):
            continue

        lines = [f"Table: {tp.name} ({tp.row_count:,} rows)"]
        for col in tp.columns:
            if col.name.startswith("_"):
                continue
            # Skip garbage columns (QR codes, JWT tokens, hashes)
            if _is_skip_column(col):
                continue
            detail = f"  - {col.name} ({col.type})"
            if col.top_values:
                # Truncate long values to save tokens
                short_vals = [v[:40] for v in col.top_values[:4]]
                detail += f" — values: {', '.join(short_vals)}"
            if col.min_val is not None:
                detail += f" — range: {col.min_val} to {col.max_val}, avg: {col.avg_val}"
            if col.null_pct > 5:
                detail += f" — {col.null_pct}% null"
            lines.append(detail)
        # Compact sample: skip fields with long values
        if tp.sample_rows:
            sample = {}
            for k, v in tp.sample_rows[0].items():
                sv = str(v)
                if len(sv) < 80 and not k.startswith("_"):
                    sample[k] = v
            sample_str = json.dumps(sample, default=str)[:300]
            lines.append(f"  Sample: {sample_str}")
        # Include detected nuances
        if tp.query_guidance:
            for g in tp.query_guidance[:3]:
                lines.append(f"  !! {g}")
        summary_parts.append("\n".join(lines))

    data_text = "\n\n".join(summary_parts)

    llm = get_worker_llm()
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Database type: {connector_label}\n\n{data_text}"),
    ]
    response = await llm.ainvoke(messages)
    text = response.content.strip()

    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM intelligence briefing response")
        return {
            "executive_summary": "",
            "data_architecture": "",
            "tables": [],
            "intelligence_playbook": [],
        }


# ── Step 5: Format profile text for LLM prompt ──────────────────

# Internal / system tables to exclude from the profile (case-insensitive prefix match)
_SKIP_TABLE_PREFIXES = (
    "chat_", "email_", "verification", "session", "migration",
    "django_", "auth_", "celery_", "pg_", "sql_", "__",
)

# Columns likely containing long garbage (QR codes, JWT tokens, hashes, encoded data)
_SKIP_COLUMN_KEYWORDS = (
    "qrcode", "qr_code", "signed_qr", "jwt", "token", "hash",
    "signature", "certificate", "encoded", "base64", "blob",
    "password", "secret", "credential",
)

# Max chars for any single top_value entry
_MAX_VALUE_LEN = 40
# Max total profile_text target (chars) — roughly 4K tokens
_MAX_PROFILE_CHARS = 16000


def _is_skip_table(name: str) -> bool:
    """Check if a table should be excluded from the profile."""
    lower = name.lower()
    return any(lower.startswith(p) for p in _SKIP_TABLE_PREFIXES)


def _is_skip_column(col: ColumnProfile) -> bool:
    """Check if a column contains long garbage data (QR codes, JWTs, etc.)."""
    lower = col.name.lower()
    if any(kw in lower for kw in _SKIP_COLUMN_KEYWORDS):
        return True
    # Detect by inspecting top_values — if any value is very long, skip
    if col.top_values:
        avg_len = sum(len(v) for v in col.top_values[:3]) / max(len(col.top_values[:3]), 1)
        if avg_len > 100:
            return True
    return False


def _truncate_value(val: str, max_len: int = _MAX_VALUE_LEN) -> str:
    """Truncate a value string, keeping it readable."""
    if len(val) <= max_len:
        return val
    return val[:max_len - 3] + "..."


def _format_profile_text(profile: DataProfile, connector_type: str) -> str:
    """Format the data profile as a compact ANALYSIS PLAN.

    Structure: Context → KPIs → Playbook → Column Reference (minimal)
    This is injected into the agent's system prompt. Targets ~3,000-4,000 tokens.
    """
    is_cosmos = "cosmos" in connector_type.lower()
    sections: list[str] = []

    # ── Header + Context ──────────────────────────────────────────────
    sections.append(f"# DATA ANALYSIS PLAN ({connector_type})")
    sections.append("")

    if profile.executive_summary:
        summary = profile.executive_summary[:400]
        if len(profile.executive_summary) > 400:
            summary = summary.rsplit(".", 1)[0] + "."
        sections.append(summary)
        sections.append("")

    # ── Filter to business tables ─────────────────────────────────────
    biz_tables = [tp for tp in profile.tables if not _is_skip_table(tp.name)]
    if not biz_tables:
        biz_tables = profile.tables

    # ── Available Data (one-liner per table) ──────────────────────────
    sections.append("## Available Data")
    for tp in biz_tables:
        desc = ""
        if tp.business_summary:
            first = tp.business_summary.split(".")[0].strip()
            if first:
                desc = f" — {first}"
        sections.append(f"- **{tp.name}** ({tp.row_count:,} rows){desc}")
    sections.append("")

    # ── KPIs (the most important section) ─────────────────────────────
    kpis = profile.cross_table_insights  # Repurposed field stores KPIs
    if kpis:
        sections.append("## Key Metrics (KPIs)")
        for kpi in kpis[:10]:
            sections.append(f"- {kpi}")
        sections.append("")

    # ── Analysis Playbook (pre-built queries) ─────────────────────────
    if profile.directional_plan:
        sections.append("## Analysis Playbook")
        sections.append("*Match user questions to these. Adapt the query as needed.*")
        sections.append("")

        for i, dq in enumerate(profile.directional_plan[:10], 1):
            title = dq.title or f"Direction {i}"
            sections.append(f"### {i}. {title}")
            sections.append(f"Q: {dq.question}")
            if dq.narrative:
                # Keep narrative to 2 sentences max
                sentences = dq.narrative.split(".")
                short_narrative = ".".join(sentences[:2]).strip()
                if short_narrative:
                    sections.append(short_narrative + ".")
            if dq.query_template:
                template = dq.query_template.strip()
                if len(template) > 350:
                    template = template[:350] + "..."
                sections.append(f"```\n{template}\n```")
            sections.append("")

    # ── Column Reference (minimal — just names + types for query writing)
    sections.append("## Column Reference")
    for tp in biz_tables:
        # Build nested object map
        nested_map: dict[str, list[ColumnProfile]] = {}
        nested_child_names: set[str] = set()
        for col in tp.columns:
            if "." in col.name and not col.name.startswith("_"):
                parent = col.name.split(".")[0]
                nested_map.setdefault(parent, []).append(col)
                nested_child_names.add(col.name)

        # Collect usable columns
        usable_cols = []
        for col in tp.columns:
            if col.name.startswith("_"):
                continue
            if col.name in nested_child_names:
                continue
            if _is_skip_column(col):
                continue
            usable_cols.append(col)

        if not usable_cols:
            continue

        # Compact: table name then columns as comma-separated list
        col_parts = []
        for col in usable_cols:
            if col.name in nested_map:
                sub_names = [sf.name.split(".")[-1] for sf in nested_map[col.name][:6]]
                col_parts.append(f"{col.name}→NESTED({', '.join(sub_names)})")
            elif col.top_values:
                vals = [_truncate_value(v, 25) for v in col.top_values[:3]]
                col_parts.append(f"{col.name}({col.type}|{col.distinct_count}vals:{','.join(vals)})")
            elif col.min_val is not None:
                col_parts.append(f"{col.name}({col.type}|{col.min_val}–{col.max_val})")
            else:
                col_parts.append(f"{col.name}({col.type})")

        sections.append(f"**{tp.name}:** {', '.join(col_parts)}")
    sections.append("")

    # ── Query Notes (only critical ones) ──────────────────────────────
    all_guidance: list[str] = []
    for tp in biz_tables:
        for g in tp.query_guidance:
            if len(g) < 150:
                all_guidance.append(g)

    if all_guidance:
        sections.append("## Query Notes")
        for g in all_guidance[:6]:
            sections.append(f"- {g}")
        sections.append("")

    result = "\n".join(sections)

    # Safety: hard-truncate if still too long
    if len(result) > _MAX_PROFILE_CHARS:
        result = result[:_MAX_PROFILE_CHARS].rsplit("\n", 1)[0]
        result += "\n\n[Truncated]"

    return result


# ── Main: generate profile ───────────────────────────────────────

async def generate_workspace_profile(
    connection_id: str,
    workspace_id: str,
    connection_name: str = "",
    queue: asyncio.Queue | None = None,
) -> DataProfileDoc:
    """Generate a complete workspace intelligence profile with directional plan.

    Emits progress events to the queue if provided.
    """
    start_time = time.perf_counter()
    conn_type = _get_conn_type(connection_id)
    connector_label = _connector_label(conn_type)

    async def emit(step: str, content: str, progress: str = ""):
        if queue:
            await queue.put(AgentEvent(
                event_type=AgentEventType.thinking,
                data={"step": step, "content": content, "progress": progress},
            ))

    # Persist a "generating" placeholder so polling clients can detect in-progress state
    try:
        placeholder_doc = DataProfileDoc(
            id=f"profile-{connection_id}",
            workspace_id=workspace_id,
            connection_id=connection_id,
            connection_name=connection_name,
            connector_type=_get_conn_type(connection_id) or "",
            status="generating",
        )
        await _save_profile(placeholder_doc)
    except Exception:
        pass  # Non-critical — don't block generation

    try:
        # Step 1: Discover schema
        await emit("discover", "Discovering database schema...")
        tables = await _discover_schema(connection_id)
        await emit("discover", f"Found {len(tables)} tables/containers", f"{len(tables)} tables")

        # Step 2: Profile each table
        table_profiles: list[TableProfile] = []
        for i, table in enumerate(tables):
            await emit(
                "sampling",
                f"Profiling {table['name']}...",
                f"{i + 1}/{len(tables)}",
            )
            tp = await _profile_table(connection_id, table, conn_type)
            table_profiles.append(tp)

        # Step 3: Detect data nuances per table
        await emit("analyzing", "Detecting data nuances (arrays, nested fields, nulls)...")
        for tp in table_profiles:
            tp.query_guidance = _detect_query_guidance(
                tp, conn_type, tp.sample_rows,
            )

        # Step 4: LLM intelligence briefing synthesis
        await emit("analyzing", "Writing intelligence briefing...")
        synthesis = await _synthesize_intelligence_briefing(
            table_profiles, connector_label, conn_type,
        )

        # Merge LLM narratives into table profiles
        for tp in table_profiles:
            for syn_table in synthesis.get("tables", []):
                if syn_table.get("name") == tp.name:
                    tp.business_summary = syn_table.get("narrative", "")
                    tp.analysis_angles = syn_table.get("analysis_angles", [])
                    break

        # Parse intelligence playbook
        directional_plan: list[DirectionalQuestion] = []
        for dq_raw in synthesis.get("intelligence_playbook", []):
            try:
                directional_plan.append(DirectionalQuestion(
                    title=dq_raw.get("title", ""),
                    question=dq_raw.get("question", ""),
                    narrative=dq_raw.get("narrative", ""),
                    query_template=dq_raw.get("query_template", ""),
                    tables=dq_raw.get("tables", []),
                    key_columns=dq_raw.get("key_columns", []),
                ))
            except Exception:
                continue

        # Build DataProfile with narrative sections
        data_profile = DataProfile(
            executive_summary=synthesis.get("executive_summary", ""),
            data_architecture=synthesis.get("data_architecture", ""),
            tables=table_profiles,
            cross_table_insights=synthesis.get("kpis", synthesis.get("cross_table_insights", [])),
            suggested_questions=[dq.question for dq in directional_plan],
            directional_plan=directional_plan,
        )

        # Step 5: Format profile text
        profile_text = _format_profile_text(data_profile, connector_label)

        duration_ms = (time.perf_counter() - start_time) * 1000

        doc = DataProfileDoc(
            id=f"profile-{connection_id}",
            workspace_id=workspace_id,
            connection_id=connection_id,
            connection_name=connection_name,
            connector_type=conn_type,
            status="ready",
            profile_text=profile_text,
            raw_profile=_sanitize_for_json(data_profile.model_dump()),
            generation_duration_ms=round(duration_ms, 2),
        )

        # Store in Cosmos DB
        await _save_profile(doc)

        await emit(
            "complete",
            f"Profile ready! ({len(tables)} tables profiled, "
            f"{len(directional_plan)} questions planned in {duration_ms / 1000:.1f}s)",
        )

        return doc

    except Exception as e:
        logger.exception("Profile generation failed for connection %s", connection_id)
        duration_ms = (time.perf_counter() - start_time) * 1000

        doc = DataProfileDoc(
            id=f"profile-{connection_id}",
            workspace_id=workspace_id,
            connection_id=connection_id,
            connection_name=connection_name,
            connector_type=conn_type,
            status="failed",
            error_message=str(e),
            generation_duration_ms=round(duration_ms, 2),
        )
        await _save_profile(doc)

        if queue:
            await queue.put(AgentEvent(
                event_type=AgentEventType.error,
                data={"message": f"Profile generation failed: {e}"},
            ))

        return doc


# ── Cosmos DB persistence helpers ────────────────────────────────

def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert datetime and other non-JSON-serializable types to strings."""
    import datetime
    from decimal import Decimal
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


async def _save_profile(doc: DataProfileDoc) -> None:
    """Save or update profile document in Cosmos DB."""
    from app.db.insight_db import insight_db
    if not insight_db.is_ready:
        logger.warning("InsightDB not ready — profile not persisted")
        return
    container = insight_db.container("workspace_profiles")
    data = _sanitize_for_json(doc.model_dump())
    container.upsert_item(data)


async def load_profile(workspace_id: str, connection_id: str) -> DataProfileDoc | None:
    """Load the profile for a workspace+connection from Cosmos DB."""
    from app.db.insight_db import insight_db
    if not insight_db.is_ready:
        return None

    container = insight_db.container("workspace_profiles")
    profile_id = f"profile-{connection_id}"

    try:
        item = container.read_item(item=profile_id, partition_key=workspace_id)
        return DataProfileDoc(**item)
    except Exception:
        return None


async def delete_profile(workspace_id: str, connection_id: str) -> bool:
    """Delete a profile from Cosmos DB."""
    from app.db.insight_db import insight_db
    if not insight_db.is_ready:
        return False

    container = insight_db.container("workspace_profiles")
    profile_id = f"profile-{connection_id}"

    try:
        container.delete_item(item=profile_id, partition_key=workspace_id)
        return True
    except Exception:
        return False
