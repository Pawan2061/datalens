from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from app.schemas.connection import SchemaInfo, TableInfo, ColumnInfo


async def inspect_schema(engine: AsyncEngine, connector_type: str | None = None) -> SchemaInfo:
    """Introspect database schema - get all tables, columns, types."""
    dialect = (connector_type or engine.dialect.name or "").lower()
    tables: list[TableInfo] = []
    async with engine.connect() as conn:
        if dialect.startswith("mysql"):
            table_names = await _mysql_table_names(conn)
        elif dialect.startswith("sqlite"):
            table_names = await _sqlite_table_names(conn)
        else:
            table_names = await _postgres_table_names(conn)

        for table_name in table_names:
            if dialect.startswith("mysql"):
                columns = await _mysql_columns(conn, table_name)
            elif dialect.startswith("sqlite"):
                columns = await _sqlite_columns(conn, table_name)
            else:
                columns = await _postgres_columns(conn, table_name)
            tables.append(TableInfo(name=table_name, columns=columns))

    return SchemaInfo(tables=tables)


async def _postgres_table_names(conn) -> list[str]:
    result = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
    )
    return [row[0] for row in result.fetchall()]


async def _postgres_columns(conn, table_name: str) -> list[ColumnInfo]:
    col_result = await conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table "
            "ORDER BY ordinal_position"
        ),
        {"table": table_name},
    )
    pk_result = await conn.execute(
        text(
            "SELECT kcu.column_name FROM information_schema.key_column_usage kcu "
            "JOIN information_schema.table_constraints tc "
            "ON kcu.constraint_name = tc.constraint_name "
            "AND kcu.table_schema = tc.table_schema "
            "AND kcu.table_name = tc.table_name "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "AND tc.table_schema = 'public' AND tc.table_name = :table"
        ),
        {"table": table_name},
    )
    pk_columns = {row[0] for row in pk_result.fetchall()}
    return [
        ColumnInfo(name=row[0], type=row[1], is_primary_key=row[0] in pk_columns)
        for row in col_result.fetchall()
    ]


async def _mysql_table_names(conn) -> list[str]:
    result = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
    )
    return [row[0] for row in result.fetchall()]


async def _mysql_columns(conn, table_name: str) -> list[ColumnInfo]:
    col_result = await conn.execute(
        text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = :table "
            "ORDER BY ordinal_position"
        ),
        {"table": table_name},
    )
    pk_result = await conn.execute(
        text(
            "SELECT kcu.column_name FROM information_schema.key_column_usage kcu "
            "JOIN information_schema.table_constraints tc "
            "ON kcu.constraint_name = tc.constraint_name "
            "AND kcu.table_schema = tc.table_schema "
            "AND kcu.table_name = tc.table_name "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "AND tc.table_schema = DATABASE() AND tc.table_name = :table"
        ),
        {"table": table_name},
    )
    pk_columns = {row[0] for row in pk_result.fetchall()}
    return [
        ColumnInfo(name=row[0], type=row[1], is_primary_key=row[0] in pk_columns)
        for row in col_result.fetchall()
    ]


async def _sqlite_table_names(conn) -> list[str]:
    result = await conn.execute(
        text(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    )
    return [row[0] for row in result.fetchall()]


async def _sqlite_columns(conn, table_name: str) -> list[ColumnInfo]:
    escaped_table = table_name.replace('"', '""')
    result = await conn.execute(text(f'PRAGMA table_info("{escaped_table}")'))
    return [
        ColumnInfo(name=row[1], type=row[2], is_primary_key=bool(row[5]))
        for row in result.fetchall()
    ]


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
