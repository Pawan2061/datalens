from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from app.schemas.connection import SchemaInfo, TableInfo, ColumnInfo


async def inspect_schema(engine: AsyncEngine) -> SchemaInfo:
    """Introspect database schema - get all tables, columns, types."""
    tables: list[TableInfo] = []
    async with engine.connect() as conn:
        # Use raw SQL to get table info from information_schema
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
        )
        table_names = [row[0] for row in result.fetchall()]

        for table_name in table_names:
            # Get columns for each table
            col_result = await conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :table "
                    "ORDER BY ordinal_position"
                ),
                {"table": table_name},
            )

            # Get primary keys
            pk_result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.key_column_usage kcu "
                    "JOIN information_schema.table_constraints tc "
                    "ON kcu.constraint_name = tc.constraint_name "
                    "WHERE tc.constraint_type = 'PRIMARY KEY' "
                    "AND tc.table_schema = 'public' AND tc.table_name = :table"
                ),
                {"table": table_name},
            )
            pk_columns = {row[0] for row in pk_result.fetchall()}

            columns = [
                ColumnInfo(
                    name=row[0],
                    type=row[1],
                    is_primary_key=row[0] in pk_columns,
                )
                for row in col_result.fetchall()
            ]
            tables.append(TableInfo(name=table_name, columns=columns))

    return SchemaInfo(tables=tables)


def format_schema_for_llm(schema: SchemaInfo) -> str:
    """Format schema as concise text for LLM prompt context."""
    lines: list[str] = []
    for table in schema.tables:
        cols = ", ".join(
            f"{c.name} ({c.type}{'*, PK' if c.is_primary_key else ''})"
            for c in table.columns
        )
        lines.append(f"Table: {table.name} | Columns: {cols}")
    return "\n".join(lines)
