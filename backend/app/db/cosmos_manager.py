"""Cosmos DB connection manager + query runner + schema inspector."""

from __future__ import annotations

import logging
import time
import uuid

from azure.cosmos import CosmosClient, exceptions

logger = logging.getLogger(__name__)

from app.schemas.connection import (
    ColumnInfo,
    ConnectionConfig,
    ConnectionInfo,
    SchemaInfo,
    TableInfo,
)


class CosmosConnectionManager:
    """Manages Azure Cosmos DB connections."""

    def __init__(self) -> None:
        self._connections: dict[str, dict] = {}  # id -> {config, client, db, status}

    async def add_connection(self, config: ConnectionConfig) -> ConnectionInfo:
        conn_id = uuid.uuid4().hex[:12]

        try:
            client = CosmosClient(config.endpoint, config.account_key)
            db = client.get_database_client(config.database)
            # Test by listing containers
            list(db.list_containers(max_item_count=1))
            status = "connected"
        except Exception:
            client = None
            db = None
            status = "disconnected"

        self._connections[conn_id] = {
            "config": config,
            "client": client,
            "db": db,
            "status": status,
        }

        return ConnectionInfo(
            id=conn_id,
            name=config.name,
            connector_type="cosmosdb",
            host=config.endpoint,
            database=config.database,
            status=status,
        )

    def get_client(self, connection_id: str):
        """Return the CosmosClient for a connection, or None."""
        entry = self._connections.get(connection_id)
        return entry["client"] if entry else None

    def get_db(self, connection_id: str):
        """Return the DatabaseProxy for a connection, or None."""
        entry = self._connections.get(connection_id)
        return entry["db"] if entry else None

    def has_connection(self, connection_id: str) -> bool:
        return connection_id in self._connections

    def list_connections(self) -> list[ConnectionInfo]:
        result: list[ConnectionInfo] = []
        for conn_id, entry in self._connections.items():
            cfg = entry["config"]
            result.append(
                ConnectionInfo(
                    id=conn_id,
                    name=cfg.name,
                    connector_type="cosmosdb",
                    host=cfg.endpoint,
                    database=cfg.database,
                    status=entry["status"],
                )
            )
        return result

    async def test_connection(self, connection_id: str) -> bool:
        entry = self._connections.get(connection_id)
        if entry is None:
            return False
        try:
            db = entry["db"]
            list(db.list_containers(max_item_count=1))
            entry["status"] = "connected"
            return True
        except Exception:
            entry["status"] = "disconnected"
            return False

    async def remove_connection(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    # ── Schema Inspection ────────────────────────────────────────────

    def inspect_schema(self, connection_id: str) -> SchemaInfo:
        """Introspect Cosmos DB schema by sampling documents from each container."""
        entry = self._connections.get(connection_id)
        if not entry or not entry["db"]:
            raise ValueError(f"Connection {connection_id} not found or disconnected")

        db = entry["db"]
        tables: list[TableInfo] = []

        for container_props in db.list_containers():
            container_name = container_props["id"]
            container = db.get_container_client(container_name)

            # Sample up to 10 documents to infer schema
            sample_docs = list(container.query_items(
                query="SELECT TOP 10 * FROM c",
                enable_cross_partition_query=True,
                populate_query_metrics=True,
            ))

            if not sample_docs:
                tables.append(TableInfo(name=container_name, columns=[]))
                continue

            # Collect all unique keys and their types from sample
            key_types: dict[str, set[str]] = {}
            for doc in sample_docs:
                for key, value in doc.items():
                    if key.startswith("_"):  # Skip Cosmos system fields
                        continue
                    if key not in key_types:
                        key_types[key] = set()
                    key_types[key].add(_infer_type(value))

            columns = []
            for key, types in key_types.items():
                # Pick the most common type, prefer specific over "null"
                types.discard("null")
                col_type = ", ".join(sorted(types)) if types else "any"
                columns.append(ColumnInfo(
                    name=key,
                    type=col_type,
                    is_primary_key=(key == "id"),
                ))

            tables.append(TableInfo(name=container_name, columns=columns))

        return SchemaInfo(tables=tables)

    def format_schema_for_llm(self, connection_id: str) -> str:
        """Format Cosmos DB schema for LLM prompt injection."""
        schema = self.inspect_schema(connection_id)
        lines: list[str] = []
        for table in schema.tables:
            cols = ", ".join(
                f"{c.name} ({c.type}{'*, PK' if c.is_primary_key else ''})"
                for c in table.columns
            )
            lines.append(f"Container: {table.name} | Fields: {cols}")
        result = "\n".join(lines)
        logger.info("Schema for LLM:\n%s", result)
        return result

    # ── Query Execution ──────────────────────────────────────────────

    def execute_query(self, connection_id: str, query: str, max_rows: int = 10000) -> dict:
        """Execute a Cosmos DB SQL query and return results."""
        import re as _re
        from collections import defaultdict

        entry = self._connections.get(connection_id)
        if not entry or not entry["db"]:
            return {"data": [], "columns": [], "row_count": 0, "duration_ms": 0,
                    "error": f"Connection {connection_id} not found"}

        db = entry["db"]
        start = time.perf_counter()

        try:
            container_name = _extract_container_name(query)
            if not container_name:
                return {"data": [], "columns": [], "row_count": 0, "duration_ms": 0,
                        "error": "Could not determine container from query."}

            container = db.get_container_client(container_name)
            normalized_query = _normalize_cosmos_query(query, container_name)

            logger.info("Cosmos query — container: %s", container_name)
            logger.info("  Original:   %s", query)
            logger.info("  Normalized: %s", normalized_query)

            # Try direct execution first
            try:
                results = list(container.query_items(
                    query=normalized_query,
                    enable_cross_partition_query=True,
                ))
            except exceptions.CosmosHttpResponseError as sdk_err:
                err_msg = str(sdk_err.message) if sdk_err.message else str(sdk_err)
                # If GROUP BY not supported by SDK, do client-side aggregation
                if "GroupBy" in err_msg or "NonValueAggregate" in err_msg:
                    logger.info("  GROUP BY not supported by SDK — falling back to client-side aggregation")
                    results = self._client_side_group_by(container, normalized_query, max_rows)
                else:
                    raise  # Re-raise for other errors

            # Strip Cosmos system fields
            clean_data = []
            for doc in results[:max_rows]:
                if isinstance(doc, dict):
                    clean = {k: v for k, v in doc.items() if not k.startswith("_")}
                    clean_data.append(clean)

            columns = list(clean_data[0].keys()) if clean_data else []
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info("  Result: %d rows in %.1fms", len(clean_data), duration_ms)

            return {
                "data": clean_data, "columns": columns,
                "row_count": len(clean_data),
                "duration_ms": round(duration_ms, 2), "error": None,
            }

        except exceptions.CosmosHttpResponseError as e:
            duration_ms = (time.perf_counter() - start) * 1000
            error_msg = f"Cosmos DB error: {e.message}"
            logger.error("  Cosmos error: %s", error_msg)
            return {"data": [], "columns": [], "row_count": 0,
                    "duration_ms": round(duration_ms, 2), "error": error_msg}
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error("  Query exception: %s", e)
            return {"data": [], "columns": [], "row_count": 0,
                    "duration_ms": round(duration_ms, 2), "error": str(e)}

    def _client_side_group_by(self, container, query: str, max_rows: int) -> list[dict]:
        """Fallback: fetch raw data and do GROUP BY + aggregates in Python."""
        import re as _re
        from collections import defaultdict

        # Parse the GROUP BY fields
        gb_match = _re.search(r'GROUP\s+BY\s+(.+?)(?:\s+ORDER|\s+LIMIT|\s*$)', query, _re.IGNORECASE)
        if not gb_match:
            return []
        group_fields_raw = gb_match.group(1).strip()
        group_fields = [f.strip().replace("c.", "") for f in group_fields_raw.split(",")]

        # Parse SELECT for aggregate expressions
        sel_match = _re.search(r'SELECT\s+(.*?)\s+FROM\s+', query, _re.IGNORECASE | _re.DOTALL)
        if not sel_match:
            return []
        select_raw = sel_match.group(1).strip()

        # Build a simple fetch query (no GROUP BY, no aggregates)
        where_match = _re.search(r'(WHERE\s+.+?)(?:\s+GROUP\s+BY)', query, _re.IGNORECASE | _re.DOTALL)
        where_clause = where_match.group(1) if where_match else ""
        fetch_query = f"SELECT * FROM c {where_clause}"

        logger.info("  Fallback fetch: %s", fetch_query)
        raw_results = list(container.query_items(
            query=fetch_query,
            enable_cross_partition_query=True,
        ))
        logger.info("  Fetched %d raw documents", len(raw_results))

        # Group and aggregate in Python
        groups: dict[tuple, list] = defaultdict(list)
        for doc in raw_results:
            key = tuple(doc.get(f) for f in group_fields)
            groups[key].append(doc)

        # Parse aggregates from SELECT clause
        agg_pattern = _re.compile(
            r'(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(?:c\.)?(\w+|1)\s*\)\s*(?:AS\s+(\w+))?',
            _re.IGNORECASE
        )
        aggregates = agg_pattern.findall(select_raw)  # [(func, field, alias), ...]

        # Build result rows
        result = []
        for key_vals, docs in groups.items():
            row: dict = {}
            for i, field in enumerate(group_fields):
                row[field] = key_vals[i]
            for func, field, alias in aggregates:
                col_name = alias if alias else f"{func.lower()}_{field}"
                func_upper = func.upper()
                if func_upper == "COUNT":
                    row[col_name] = len(docs)
                elif func_upper == "SUM":
                    row[col_name] = sum(doc.get(field, 0) or 0 for doc in docs)
                elif func_upper == "AVG":
                    vals = [doc.get(field, 0) or 0 for doc in docs]
                    row[col_name] = sum(vals) / len(vals) if vals else 0
                elif func_upper == "MIN":
                    vals = [doc.get(field) for doc in docs if doc.get(field) is not None]
                    row[col_name] = min(vals) if vals else None
                elif func_upper == "MAX":
                    vals = [doc.get(field) for doc in docs if doc.get(field) is not None]
                    row[col_name] = max(vals) if vals else None
            result.append(row)

        # Handle ORDER BY if present
        order_match = _re.search(r'ORDER\s+BY\s+(?:c\.)?(\w+)(?:\s+(ASC|DESC))?', query, _re.IGNORECASE)
        if order_match:
            sort_field = order_match.group(1)
            descending = (order_match.group(2) or "").upper() == "DESC"
            result.sort(key=lambda r: r.get(sort_field) or 0, reverse=descending)

        return result[:max_rows]


def _infer_type(value) -> str:
    """Infer a JSON-friendly type label for a value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "any"


def _extract_container_name(query: str) -> str | None:
    """Extract container name from a Cosmos SQL query like 'SELECT ... FROM accuracy_report ...'."""
    import re
    # Match FROM <name> where name is not 'c' (Cosmos alias)
    match = re.search(r'\bFROM\s+(\w+)', query, re.IGNORECASE)
    if match:
        name = match.group(1)
        if name.lower() != "c":
            return name
    return None


def _normalize_cosmos_query(query: str, container_name: str) -> str:
    """Replace container name with 'c' alias for Cosmos DB execution.

    Cosmos SQL queries run against a container, so FROM should use 'c'
    and all field references should use c.field_name.
    """
    import re

    # Replace 'FROM container_name [alias]' with 'FROM c'
    # Handles: FROM bucket_report, FROM bucket_report c, FROM bucket_report AS c
    normalized = re.sub(
        rf'\bFROM\s+{re.escape(container_name)}(\s+AS\s+\w+|\s+[a-zA-Z]\b)?',
        'FROM c',
        query,
        flags=re.IGNORECASE,
    )

    # Replace 'container_name.' with 'c.' for field references
    normalized = re.sub(
        rf'\b{re.escape(container_name)}\.',
        'c.',
        normalized,
        flags=re.IGNORECASE,
    )

    # Fix any bare field references without c. prefix in SELECT/WHERE/GROUP BY
    # e.g., "SELECT bucket" → "SELECT c.bucket" (only if field isn't already prefixed)
    # Skip SQL keywords and aggregate functions
    _SQL_KEYWORDS = {
        'select', 'from', 'where', 'group', 'by', 'order', 'as', 'and', 'or',
        'not', 'in', 'is', 'null', 'true', 'false', 'top', 'asc', 'desc',
        'count', 'sum', 'avg', 'min', 'max', 'value', 'distinct', 'between',
        'like', 'array_length', 'array_contains', 'contains', 'lower', 'upper',
        'round', 'abs', 'floor', 'ceiling', 'is_defined', 'startswith',
    }

    # Remove column alias conflicts: 'c c' at word boundary
    normalized = re.sub(r'\bFROM\s+c\s+c\b', 'FROM c', normalized, flags=re.IGNORECASE)

    return normalized


# Singleton
cosmos_manager = CosmosConnectionManager()
