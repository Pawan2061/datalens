"""PostgreSQL-backed persistence for DataLens app data.

Provides a Cosmos-SDK-compatible interface (PGContainer) so all existing
call sites work unchanged. Only insight_db.py itself was rewritten.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.config import settings

# ---------------------------------------------------------------------------
# JSONB columns per table — values are serialized as JSON on write and
# psycopg3 deserializes them automatically on read.
# ---------------------------------------------------------------------------
_JSONB_COLS: dict[str, set[str]] = {
    "workspaces": {"connection_ids", "connections", "members", "api_tools", "scope_customers"},
    "sessions": {"messages"},
    "canvas_states": {"blocks"},
    "connections": {"config"},
    "workspace_profiles": {"raw_profile"},
}

# ---------------------------------------------------------------------------
# DDL — all tables created with IF NOT EXISTS on startup
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL DEFAULT '' UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'pending',
    max_questions_per_day INTEGER NOT NULL DEFAULT 0,
    max_tokens_per_day INTEGER NOT NULL DEFAULT 0,
    max_cost_usd_per_month DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    expiry_date TEXT NOT NULL DEFAULT '',
    total_questions INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    today_questions INTEGER NOT NULL DEFAULT 0,
    today_tokens INTEGER NOT NULL DEFAULT 0,
    today_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    month_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    usage_reset_date TEXT NOT NULL DEFAULT '',
    month_reset_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '',
    last_login_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    icon TEXT NOT NULL DEFAULT '',
    connection_ids JSONB NOT NULL DEFAULT '[]',
    connections JSONB NOT NULL DEFAULT '[]',
    scope_customers JSONB NOT NULL DEFAULT '[]',
    members JSONB NOT NULL DEFAULT '[]',
    api_tools JSONB NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    last_active_at TEXT NOT NULL DEFAULT ''
);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS scope_customers JSONB NOT NULL DEFAULT '[]';
CREATE INDEX IF NOT EXISTS idx_workspaces_owner_id ON workspaces (owner_id);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT 'New Chat',
    messages JSONB NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace_id ON sessions (workspace_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions (user_id);

CREATE TABLE IF NOT EXISTS canvas_states (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    blocks JSONB NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS connections (
    id TEXT PRIMARY KEY,
    connector_type TEXT NOT NULL DEFAULT '',
    config JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS workspace_profiles (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    connection_id TEXT NOT NULL DEFAULT '',
    connection_name TEXT NOT NULL DEFAULT '',
    connector_type TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    profile_text TEXT NOT NULL DEFAULT '',
    raw_profile JSONB NOT NULL DEFAULT '{}',
    generated_at TEXT NOT NULL DEFAULT '',
    generation_duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    error_message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_workspace_profiles_workspace_id ON workspace_profiles (workspace_id);

CREATE TABLE IF NOT EXISTS usage_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    questions INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    model_name TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_usage_logs_user_id ON usage_logs (user_id);

CREATE TABLE IF NOT EXISTS analytics_events (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    user_email TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL DEFAULT '',
    query_text TEXT NOT NULL DEFAULT '',
    connection_id TEXT NOT NULL DEFAULT '',
    analysis_mode TEXT NOT NULL DEFAULT '',
    tokens_used INTEGER NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    model_name TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_analytics_events_workspace_id ON analytics_events (workspace_id);
CREATE INDEX IF NOT EXISTS idx_analytics_events_timestamp ON analytics_events (timestamp);
"""


# ---------------------------------------------------------------------------
# Cosmos-SQL → PostgreSQL query translator
# ---------------------------------------------------------------------------

def _translate_query(
    table: str,
    cosmos_query: str,
    parameters: list[dict] | None,
) -> tuple[str, dict]:
    """Translate a Cosmos SQL query string + parameters to PostgreSQL.

    Cosmos queries look like:
        SELECT * FROM c WHERE c.email = @email ORDER BY c.created_at DESC

    Returns (pg_sql, params_dict) ready for psycopg3 named-placeholder execution.
    """
    q = cosmos_query.strip()

    # Replace FROM c  (word boundary so we don't clobber FROM canvas etc.)
    q = re.sub(r'\bFROM\s+c\b', f'FROM {table}', q)

    # Strip c. prefix from field references (SELECT c.foo, WHERE c.foo, ORDER BY c.foo)
    q = re.sub(r'\bc\.(\w+)', r'\1', q)

    # Convert @paramname → %(paramname)s
    q = re.sub(r'@(\w+)', r'%(\1)s', q)

    # Build params dict from Cosmos parameters list
    params: dict[str, Any] = {}
    if parameters:
        for p in parameters:
            name = p["name"].lstrip("@")
            params[name] = p["value"]

    return q, params


# ---------------------------------------------------------------------------
# PGContainer — Cosmos SDK-compatible proxy backed by psycopg3
# ---------------------------------------------------------------------------

class PGContainer:
    def __init__(self, table: str, pool):
        self._table = table
        self._pool = pool
        self._jsonb = _JSONB_COLS.get(table, set())

    # ── helpers ──────────────────────────────────────────────────────────

    def _row_to_dict(self, row, description) -> dict:
        doc = {}
        for col, val in zip(description, row):
            name = col.name
            # psycopg3 returns JSONB as Python objects natively; TEXT columns
            # that happen to contain JSON are returned as strings — no conversion needed.
            doc[name] = val
        return doc

    def _serialize_doc(self, doc: dict) -> dict:
        """JSON-encode JSONB columns before INSERT/UPDATE."""
        out = {}
        for k, v in doc.items():
            if k in self._jsonb and not isinstance(v, str):
                out[k] = json.dumps(v)
            else:
                out[k] = v
        return out

    # ── public Cosmos-compatible API ─────────────────────────────────────

    def query_items(
        self,
        query: str,
        parameters: list[dict] | None = None,
        enable_cross_partition_query: bool | None = None,
        partition_key: Any = None,
    ):
        """Translate Cosmos SQL and execute against PostgreSQL. Returns a list."""
        pg_sql, params = _translate_query(self._table, query, parameters)
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(pg_sql, params or None)
                if cur.description is None:
                    return []
                return [self._row_to_dict(row, cur.description) for row in cur.fetchall()]

    def read_item(self, item: str, partition_key: Any = None) -> dict:
        """Fetch a single document by id."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {self._table} WHERE id = %s", (item,))
                if cur.description is None or cur.rowcount == 0:
                    raise KeyError(f"{self._table}: item {item!r} not found")
                row = cur.fetchone()
                if row is None:
                    raise KeyError(f"{self._table}: item {item!r} not found")
                return self._row_to_dict(row, cur.description)

    def upsert_item(self, doc: dict) -> dict:
        """INSERT … ON CONFLICT (id) DO UPDATE — full document replace."""
        if "id" not in doc or doc["id"] is None:
            doc = {**doc, "id": uuid.uuid4().hex[:12]}
        d = self._serialize_doc(doc)
        cols = list(d.keys())
        placeholders = [f"%({c})s" for c in cols]
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "id")
        sql = (
            f"INSERT INTO {self._table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(placeholders)}) "
            f"ON CONFLICT (id) DO UPDATE SET {updates}"
        )
        with self._pool.connection() as conn:
            conn.execute(sql, d)
        return doc

    def create_item(self, doc: dict) -> dict:
        """INSERT a new document. Generates id if missing."""
        if "id" not in doc or doc["id"] is None:
            doc = {**doc, "id": uuid.uuid4().hex[:12]}
        d = self._serialize_doc(doc)
        cols = list(d.keys())
        placeholders = [f"%({c})s" for c in cols]
        sql = (
            f"INSERT INTO {self._table} ({', '.join(cols)}) "
            f"VALUES ({', '.join(placeholders)})"
        )
        with self._pool.connection() as conn:
            conn.execute(sql, d)
        return doc

    def delete_item(self, item: str, partition_key: Any = None) -> None:
        """Delete a document by id."""
        with self._pool.connection() as conn:
            conn.execute(f"DELETE FROM {self._table} WHERE id = %s", (item,))

    def read_all_items(self):
        """Return all documents in the table."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {self._table}")
                if cur.description is None:
                    return []
                return [self._row_to_dict(row, cur.description) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# InsightDB — singleton, initialized at app startup
# ---------------------------------------------------------------------------

class InsightDB:
    """PostgreSQL-backed persistence for DataLens app data."""

    def __init__(self):
        self._pool = None

    def initialize(self):
        """Open connection pool and create tables. Called at app startup."""
        url = settings.database_url
        if not url:
            print("WARNING: DATABASE_URL not configured. Persistence disabled.")
            print("  Set DATABASE_URL=postgresql+psycopg://user:pass@host/db in .env")
            return

        # Strip SQLAlchemy dialect prefix if present so psycopg_pool gets a plain DSN
        dsn = re.sub(r'^postgresql\+psycopg://', 'postgresql://', url)

        try:
            from psycopg_pool import ConnectionPool
            self._pool = ConnectionPool(dsn, min_size=1, max_size=10, open=True)

            # Create tables — execute each statement individually (psycopg3
            # does not allow multiple statements in a single execute() call)
            with self._pool.connection() as conn:
                for stmt in _DDL.split(';'):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)

            print("InsightDB initialized: connected to PostgreSQL")
        except Exception as e:
            print(f"WARNING: Failed to connect to PostgreSQL: {e}")
            print("  Persistence will be disabled. The app will still run.")
            self._pool = None

    @property
    def is_ready(self) -> bool:
        return self._pool is not None

    def container(self, name: str) -> PGContainer:
        if not self.is_ready:
            raise RuntimeError("InsightDB not initialized")
        return PGContainer(name, self._pool)


insight_db = InsightDB()
