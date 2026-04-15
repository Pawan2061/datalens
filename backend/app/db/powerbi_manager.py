"""Power BI connection manager — auth, schema discovery, DAX execution."""

from __future__ import annotations

import logging
import re
import time
import uuid

import httpx

logger = logging.getLogger(__name__)

from app.schemas.connection import (
    ColumnInfo,
    ConnectionConfig,
    ConnectionInfo,
    SchemaInfo,
    TableInfo,
)

_PBI_BASE = "https://api.powerbi.com/v1.0/myorg"
_SCOPE = "https://analysis.windows.net/powerbi/api/.default"


class PowerBIConnectionManager:
    """Manages Power BI connections via REST API + service principal auth."""

    def __init__(self) -> None:
        self._connections: dict[str, dict] = {}  # id -> {config, token, token_expires, status}

    # ── Token management ──────────────────────────────────────────────

    def _acquire_token(self, config: ConnectionConfig) -> str:
        """Acquire an Azure AD access token using MSAL client credentials."""
        from msal import ConfidentialClientApplication

        app = ConfidentialClientApplication(
            client_id=config.client_id,
            authority=f"https://login.microsoftonline.com/{config.tenant_id}",
            client_credential=config.client_secret,
        )
        result = app.acquire_token_for_client(scopes=[_SCOPE])
        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown auth error"))
            raise RuntimeError(f"Power BI auth failed: {error}")
        return result["access_token"]

    def _get_token(self, connection_id: str) -> str:
        """Get a valid access token, refreshing if expired."""
        entry = self._connections.get(connection_id)
        if not entry:
            raise ValueError(f"Connection {connection_id} not found")

        # MSAL handles token caching internally, but we cache at our level too
        now = time.time()
        if entry.get("token") and entry.get("token_expires", 0) > now:
            return entry["token"]

        token = self._acquire_token(entry["config"])
        entry["token"] = token
        entry["token_expires"] = now + 3000  # ~50 min (tokens last ~60min)
        return token

    def _headers(self, connection_id: str) -> dict[str, str]:
        """Build authorization headers."""
        return {
            "Authorization": f"Bearer {self._get_token(connection_id)}",
            "Content-Type": "application/json",
        }

    # ── Connection lifecycle ──────────────────────────────────────────

    async def add_connection(self, config: ConnectionConfig) -> ConnectionInfo:
        conn_id = uuid.uuid4().hex[:12]

        try:
            token = self._acquire_token(config)
            # Test access by listing datasets in the workspace
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{_PBI_BASE}/groups/{config.pbi_workspace_id}/datasets",
                    headers=headers,
                )
                resp.raise_for_status()
            status = "connected"
        except Exception as e:
            logger.error("Power BI connection failed: %s", e)
            token = None
            status = "disconnected"

        self._connections[conn_id] = {
            "config": config,
            "token": token,
            "token_expires": time.time() + 3000 if token else 0,
            "status": status,
        }

        return ConnectionInfo(
            id=conn_id,
            name=config.name,
            connector_type="powerbi",
            host="app.powerbi.com",
            database=config.dataset_id,
            status=status,
        )

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
                    connector_type="powerbi",
                    host="app.powerbi.com",
                    database=cfg.dataset_id,
                    status=entry["status"],
                )
            )
        return result

    async def test_connection(self, connection_id: str) -> bool:
        entry = self._connections.get(connection_id)
        if entry is None:
            return False
        try:
            cfg = entry["config"]
            headers = self._headers(connection_id)
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{_PBI_BASE}/groups/{cfg.pbi_workspace_id}/datasets",
                    headers=headers,
                )
                resp.raise_for_status()
            entry["status"] = "connected"
            return True
        except Exception:
            entry["status"] = "disconnected"
            return False

    async def remove_connection(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    # ── Schema Inspection ─────────────────────────────────────────────

    def inspect_schema(self, connection_id: str) -> SchemaInfo:
        """Discover schema by executing INFO.TABLES() and INFO.COLUMNS() DAX queries."""
        entry = self._connections.get(connection_id)
        if not entry:
            raise ValueError(f"Connection {connection_id} not found")

        cfg = entry["config"]
        headers = self._headers(connection_id)

        # Get tables
        tables_data = self._execute_dax_raw(
            cfg.pbi_workspace_id, cfg.dataset_id, "EVALUATE INFO.TABLES()", headers
        )
        # Get columns
        columns_data = self._execute_dax_raw(
            cfg.pbi_workspace_id, cfg.dataset_id, "EVALUATE INFO.COLUMNS()", headers
        )

        # Build table → columns mapping
        # INFO.COLUMNS() returns rows like: {[TableID], [ExplicitName], [DataType], ...}
        table_id_to_name: dict[int, str] = {}
        for row in tables_data:
            tid = row.get("ID") or row.get("[ID]")
            tname = row.get("Name") or row.get("[Name]") or ""
            if tid is not None and tname:
                table_id_to_name[tid] = tname

        table_columns: dict[str, list[ColumnInfo]] = {}
        for row in columns_data:
            tid = row.get("TableID") or row.get("[TableID]")
            cname = row.get("ExplicitName") or row.get("[ExplicitName]") or ""
            ctype = row.get("DataType") or row.get("[DataType]") or "any"
            if not cname or cname.startswith("RowNumber"):
                continue
            tname = table_id_to_name.get(tid, "Unknown")
            if tname not in table_columns:
                table_columns[tname] = []
            table_columns[tname].append(ColumnInfo(
                name=cname,
                type=_map_pbi_type(ctype),
                is_primary_key=False,
            ))

        tables: list[TableInfo] = []
        for tname in sorted(table_columns.keys()):
            tables.append(TableInfo(name=tname, columns=table_columns[tname]))

        # Also add tables that have no columns (rare but possible)
        for tid, tname in table_id_to_name.items():
            if tname not in table_columns:
                tables.append(TableInfo(name=tname, columns=[]))

        return SchemaInfo(tables=tables)

    def format_schema_for_llm(self, connection_id: str) -> str:
        """Format Power BI schema as LLM-readable text."""
        schema = self.inspect_schema(connection_id)
        lines: list[str] = ["POWER BI DATASET SCHEMA:"]
        for table in schema.tables:
            cols = ", ".join(
                f"{c.name} ({c.type})" for c in table.columns
            )
            lines.append(f"Table: {table.name} | Columns: {cols}")
        result = "\n".join(lines)
        logger.info("Power BI schema for LLM:\n%s", result)
        return result

    # ── Query Execution ───────────────────────────────────────────────

    def execute_query(self, connection_id: str, dax_query: str, max_rows: int = 10000) -> dict:
        """Execute a DAX query via the Power BI REST API."""
        entry = self._connections.get(connection_id)
        if not entry:
            return {"data": [], "columns": [], "row_count": 0, "duration_ms": 0,
                    "error": f"Connection {connection_id} not found"}

        cfg = entry["config"]
        headers = self._headers(connection_id)
        start = time.perf_counter()

        try:
            raw_rows = self._execute_dax_raw(
                cfg.pbi_workspace_id, cfg.dataset_id, dax_query, headers
            )

            # Clean column names: "Table[Column]" → "Column"
            clean_data = []
            for row in raw_rows[:max_rows]:
                clean_row = {}
                for k, v in row.items():
                    clean_key = _clean_column_name(k)
                    clean_row[clean_key] = v
                clean_data.append(clean_row)

            columns = list(clean_data[0].keys()) if clean_data else []
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info("Power BI DAX: %d rows in %.1fms", len(clean_data), duration_ms)

            return {
                "data": clean_data, "columns": columns,
                "row_count": len(clean_data),
                "duration_ms": round(duration_ms, 2), "error": None,
            }

        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            error_msg = str(e)
            logger.error("Power BI DAX error: %s", error_msg)
            return {"data": [], "columns": [], "row_count": 0,
                    "duration_ms": round(duration_ms, 2), "error": error_msg}

    # ── Internal helpers ──────────────────────────────────────────────

    def _execute_dax_raw(
        self, workspace_id: str, dataset_id: str, dax: str, headers: dict
    ) -> list[dict]:
        """Execute a DAX query and return raw rows from the response."""
        url = f"{_PBI_BASE}/groups/{workspace_id}/datasets/{dataset_id}/executeQueries"
        body = {
            "queries": [{"query": dax}],
            "serializerSettings": {"includeNulls": True},
        }

        with httpx.Client(timeout=120) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()

        data = resp.json()

        # Extract rows from response
        # Response shape: {"results": [{"tables": [{"rows": [...]}]}]}
        rows: list[dict] = []
        for result in data.get("results", []):
            for table in result.get("tables", []):
                rows.extend(table.get("rows", []))

        return rows


def _clean_column_name(name: str) -> str:
    """Strip Power BI table prefix from column names.

    'Sales[Amount]' → 'Amount'
    '[Amount]' → 'Amount'
    'Amount' → 'Amount' (no change)
    """
    # Match Table[Column] or [Column]
    m = re.match(r'^(?:\w+)?\[(.+)\]$', name)
    return m.group(1) if m else name


def _map_pbi_type(data_type) -> str:
    """Map Power BI data types to simple type labels."""
    dt = str(data_type).lower()
    type_map = {
        "6": "integer",     # Int64
        "8": "number",      # Double
        "9": "datetime",    # DateTime
        "10": "decimal",    # Decimal
        "11": "boolean",    # Boolean
        "2": "string",      # String
        "1": "string",      # Text
        "17": "binary",     # Binary
    }
    # data_type might be a numeric code or a string label
    if dt in type_map:
        return type_map[dt]
    if "int" in dt:
        return "integer"
    if "double" in dt or "float" in dt or "decimal" in dt:
        return "number"
    if "date" in dt or "time" in dt:
        return "datetime"
    if "bool" in dt:
        return "boolean"
    if "string" in dt or "text" in dt:
        return "string"
    return "any"


# Singleton
powerbi_manager = PowerBIConnectionManager()
