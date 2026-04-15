from __future__ import annotations

import io
import logging
import os
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agent.schema_cache import schema_cache
from app.db.connection_manager import connection_manager
from app.db.schema_inspector import inspect_schema
from app.schemas.connection import ConnectionConfig, ConnectionInfo, SchemaInfo

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/api/connections", response_model=ConnectionInfo)
async def add_connection(config: ConnectionConfig):
    """Register a new database connection."""
    info = await connection_manager.add_connection(config)
    return info


@router.post("/api/connections/upload", response_model=ConnectionInfo)
async def upload_file_connection(
    file: UploadFile = File(...),
    name: str = Form(""),
    connectorType: str = Form("file"),
    fileFormat: str = Form("csv"),
):
    """Upload a CSV/Excel/JSON file and create a queryable SQLite connection."""
    import pandas as pd
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text as sql_text

    conn_id = uuid.uuid4().hex[:12]
    file_name = file.filename or f"upload_{conn_id}"
    display_name = name or file_name

    # Read file into DataFrame
    content = await file.read()
    try:
        if fileFormat == "excel" or file_name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        elif fileFormat == "json" or file_name.endswith(".json"):
            df = pd.read_json(io.BytesIO(content))
        else:
            df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="File contains no data")

    # Sanitize table name
    table_name = (
        os.path.splitext(file_name)[0]
        .replace(" ", "_").replace("-", "_").replace(".", "_")
        .lower()[:60]
    )
    if not table_name[0].isalpha():
        table_name = "t_" + table_name

    # Write to SQLite database file
    db_path = os.path.join(UPLOAD_DIR, f"{conn_id}.db")
    sqlite_url_sync = f"sqlite:///{db_path}"

    import sqlalchemy
    sync_engine = sqlalchemy.create_engine(sqlite_url_sync)
    df.to_sql(table_name, sync_engine, index=False, if_exists="replace")
    sync_engine.dispose()

    # Create async engine for queries
    aiosqlite_url = f"sqlite+aiosqlite:///{db_path}"
    async_engine = create_async_engine(aiosqlite_url)

    # Verify it works
    try:
        async with async_engine.connect() as conn:
            result = await conn.execute(sql_text(f"SELECT COUNT(*) FROM [{table_name}]"))
            row_count = result.scalar()
        status = "connected"
    except Exception:
        status = "disconnected"
        row_count = 0

    # Register in connection manager
    config = ConnectionConfig(
        connector_type="file", name=display_name,
        host="local", database=db_path,
    )
    connection_manager._connections[conn_id] = {
        "config": config,
        "engine": async_engine,
        "status": status,
        "type": "file",
    }

    # Persist
    from app.db.connection_store import save_connection
    save_connection(conn_id, config, "file")

    logger.info("File upload: %s -> %s (%d rows in table '%s')", file_name, conn_id, row_count, table_name)

    return ConnectionInfo(
        id=conn_id, name=display_name,
        connector_type="file", host="local",
        database=table_name, status=status,
    )


@router.get("/api/connections", response_model=list[ConnectionInfo])
async def list_connections():
    """Return all registered connections (without passwords)."""
    return connection_manager.list_connections()


@router.post("/api/connections/{connection_id}/test")
async def test_connection(connection_id: str):
    """Test whether a connection is alive."""
    if not connection_manager.has_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    ok = await connection_manager.test_connection(connection_id)
    return {"status": "connected" if ok else "disconnected"}


@router.delete("/api/connections/{connection_id}", status_code=204)
async def remove_connection(connection_id: str):
    """Remove a database connection."""
    if not connection_manager.has_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    schema_cache.invalidate(connection_id)
    await connection_manager.remove_connection(connection_id)


@router.get("/api/connections/{connection_id}/schema", response_model=SchemaInfo)
async def get_schema(connection_id: str):
    """Return the database schema for a given connection."""
    conn_type = connection_manager.get_connection_type(connection_id)
    if conn_type is None:
        raise HTTPException(status_code=404, detail="Connection not found")

    if conn_type == "cosmosdb":
        from app.db.cosmos_manager import cosmos_manager
        return cosmos_manager.inspect_schema(connection_id)

    if conn_type == "powerbi":
        from app.db.powerbi_manager import powerbi_manager
        return powerbi_manager.inspect_schema(connection_id)

    if conn_type == "file":
        engine = connection_manager.get_engine(connection_id)
        if engine is None:
            raise HTTPException(status_code=404, detail="File connection engine not found")
        schema = await inspect_schema(engine)
        return schema

    engine = connection_manager.get_engine(connection_id)
    if engine is None:
        raise HTTPException(status_code=404, detail="Connection engine not found")
    schema = await inspect_schema(engine)
    return schema
