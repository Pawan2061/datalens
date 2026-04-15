from __future__ import annotations
import asyncio
import time
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from app.config import settings


class QueryRunner:
    """Executes SQL queries safely against user databases."""

    @staticmethod
    def validate_sql(sql: str) -> None:
        """Only allow SELECT statements. Raises ValueError for DDL/DML."""
        stripped = sql.strip().upper()
        if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
            raise ValueError(f"Only SELECT queries allowed. Got: {stripped[:20]}...")

        forbidden = [
            "INSERT",
            "UPDATE",
            "DELETE",
            "DROP",
            "ALTER",
            "CREATE",
            "TRUNCATE",
            "EXEC",
            "EXECUTE",
        ]
        # Check for forbidden keywords that aren't inside quotes
        for keyword in forbidden:
            # Simple check - look for keyword as whole word
            if f" {keyword} " in f" {stripped} ":
                raise ValueError(f"Forbidden SQL keyword: {keyword}")

    @staticmethod
    async def execute(
        engine: AsyncEngine, sql: str, timeout: int | None = None
    ) -> dict:
        """Execute a SQL query and return results as list of dicts with metadata."""
        QueryRunner.validate_sql(sql)

        timeout = timeout or settings.max_query_timeout_seconds
        start = time.perf_counter()

        try:
            async with engine.connect() as conn:
                result = await asyncio.wait_for(
                    conn.execute(text(sql)),
                    timeout=timeout,
                )
                rows = result.fetchmany(settings.max_query_rows)
                columns = list(result.keys())
                data = [dict(zip(columns, row)) for row in rows]

                duration_ms = (time.perf_counter() - start) * 1000
                return {
                    "data": data,
                    "columns": columns,
                    "row_count": len(data),
                    "duration_ms": round(duration_ms, 2),
                    "error": None,
                }
        except asyncio.TimeoutError:
            return {
                "data": [],
                "columns": [],
                "row_count": 0,
                "duration_ms": (time.perf_counter() - start) * 1000,
                "error": f"Query timed out after {timeout}s",
            }
        except Exception as e:
            return {
                "data": [],
                "columns": [],
                "row_count": 0,
                "duration_ms": (time.perf_counter() - start) * 1000,
                "error": str(e),
            }
