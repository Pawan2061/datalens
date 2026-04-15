from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.llm.openai_llm import get_worker_llm

_POSTGRES_SQL_PROMPT = """\
You are a SQL expert. Generate a single valid PostgreSQL SELECT query for the \
given analytical question. The database schema is provided below.

Rules:
- Output ONLY the raw SQL query, no markdown fences, no explanation.
- Use only SELECT statements. Never use INSERT, UPDATE, DELETE, DROP, or ALTER.
- Use table and column names exactly as provided in the schema.
- Use appropriate aggregations, GROUP BY, ORDER BY, and LIMIT where needed.
- For date/time operations use PostgreSQL functions (DATE_TRUNC, EXTRACT, etc.).
- If the question is ambiguous, make reasonable assumptions and write the query.
"""

_COSMOS_SQL_PROMPT = """\
You are a Cosmos DB SQL expert. Generate a single valid Azure Cosmos DB SQL query \
for the given analytical question. The container schema (inferred from documents) \
is provided below.

CRITICAL Cosmos DB SQL rules:
- Output ONLY the raw SQL query, no markdown fences, no explanation.
- Use only SELECT statements.
- FROM must reference the container name (e.g. FROM accuracy_report).
- Field access: ALWAYS use c.field_name (e.g. c.bucket, c.header_accuracy_pct).
  The 'c' is the implicit alias for the container.
- GROUP BY is supported: SELECT c.bucket, COUNT(1) as cnt FROM accuracy_report GROUP BY c.bucket
- Aggregates: COUNT(1), SUM(c.field), AVG(c.field), MIN(c.field), MAX(c.field)
- WHERE for filtering: WHERE c.bucket = 'Ready to Post'
- ORDER BY for sorting: ORDER BY c.header_accuracy_pct DESC
- TOP N for pagination: SELECT TOP 10 * FROM accuracy_report
- Nested fields use dot notation: c.field_level_accuracy.company_code
- Arrays: ARRAY_LENGTH(c.error_reason_list), ARRAY_CONTAINS(c.list, 'value')
- String functions: CONTAINS(c.field, 'text'), LOWER(c.field), UPPER(c.field)
- Math functions: ROUND(c.field, 2), ABS(c.field)
- IS_DEFINED(c.field) to check if field exists.

NOT SUPPORTED in Cosmos DB (NEVER use these):
- NO subqueries (no nested SELECT inside SELECT or WHERE)
- NO JOINs between containers (query one container at a time)
- NO HAVING clause
- NO UNION / INTERSECT / EXCEPT
- NO window functions (ROW_NUMBER, RANK, etc.)
- NO CTEs (WITH clause)
- NO CASE WHEN expressions
- For percentages, just get counts per group — the app will calculate percentages.
- If the question is ambiguous, make reasonable assumptions and write the query.
"""


@tool
async def write_sql(description: str, schema_context: str) -> str:
    """Generate a SQL SELECT query for a specific analytical question.

    Args:
        description: What the query should compute, e.g.
            "total revenue by category for Q4 2024".
        schema_context: The database schema text (tables and columns).
            If it mentions 'Container:' it's Cosmos DB, otherwise PostgreSQL.

    Returns:
        A valid SQL SELECT query string.
    """
    # Auto-detect Cosmos DB vs PostgreSQL from schema format
    is_cosmos = "Container:" in schema_context
    base_prompt = _COSMOS_SQL_PROMPT if is_cosmos else _POSTGRES_SQL_PROMPT

    llm = get_worker_llm()
    messages = [
        SystemMessage(content=base_prompt + "\n\nSCHEMA:\n" + schema_context),
        HumanMessage(content=f"Write a SQL query for: {description}"),
    ]
    response = await llm.ainvoke(messages)
    sql = response.content.strip()

    # Strip markdown fences if the model wraps them
    if sql.startswith("```"):
        lines = sql.split("\n")
        lines = [l for l in lines if not l.startswith("```")]
        sql = "\n".join(lines).strip()

    return sql
