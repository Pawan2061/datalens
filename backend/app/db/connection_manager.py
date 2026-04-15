from __future__ import annotations
import logging
import uuid
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from app.schemas.connection import ConnectionConfig, ConnectionInfo

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages user database connections (SQL + Cosmos DB + Power BI)."""

    def __init__(self):
        self._connections: dict[str, dict] = {}  # id -> {config, engine?, status, type}

    # ── Persistence: restore saved connections on startup ──────────
    async def restore_connections(self) -> None:
        """Reload all persisted connections from the Cosmos DB store."""
        from app.db.connection_store import load_all

        saved = load_all()
        if not saved:
            logger.info("No saved connections to restore")
            return

        restored = 0
        for item in saved:
            conn_id = item.get("id")
            config_dict = item.get("config")
            conn_type = item.get("connector_type")
            if not conn_id or not config_dict:
                continue

            try:
                config = ConnectionConfig(**config_dict)
                if conn_type == "cosmosdb":
                    await self._restore_cosmos(conn_id, config)
                elif conn_type == "powerbi":
                    await self._restore_powerbi(conn_id, config)
                elif conn_type == "file":
                    await self._restore_file(conn_id, config)
                else:
                    await self._restore_sql(conn_id, config)
                restored += 1
            except Exception as e:
                logger.warning("Failed to restore connection %s: %s", conn_id, e)

        logger.info("Restored %d/%d connections from store", restored, len(saved))

    async def _restore_sql(self, conn_id: str, config: ConnectionConfig) -> None:
        url = (
            f"postgresql+asyncpg://{config.user}:{config.password}"
            f"@{config.host}:{config.port}/{config.database}"
        )
        engine = create_async_engine(url, pool_size=5, max_overflow=2)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            status = "connected"
        except Exception:
            status = "disconnected"

        self._connections[conn_id] = {
            "config": config, "engine": engine,
            "status": status, "type": config.connector_type,
        }

    async def _restore_cosmos(self, conn_id: str, config: ConnectionConfig) -> None:
        from azure.cosmos import CosmosClient
        from app.db.cosmos_manager import cosmos_manager

        try:
            client = CosmosClient(config.endpoint, config.account_key)
            db = client.get_database_client(config.database)
            list(db.list_containers(max_item_count=1))
            status = "connected"
        except Exception:
            client, db, status = None, None, "disconnected"

        cosmos_manager._connections[conn_id] = {
            "config": config, "client": client, "db": db, "status": status,
        }
        self._connections[conn_id] = {
            "config": config, "status": status, "type": "cosmosdb",
        }

    async def _restore_powerbi(self, conn_id: str, config: ConnectionConfig) -> None:
        from app.db.powerbi_manager import powerbi_manager

        try:
            token = powerbi_manager._acquire_token(config)
            status = "connected"
        except Exception:
            token = None
            status = "disconnected"

        import time
        powerbi_manager._connections[conn_id] = {
            "config": config, "token": token,
            "token_expires": time.time() + 3000 if token else 0,
            "status": status,
        }
        self._connections[conn_id] = {
            "config": config, "status": status, "type": "powerbi",
        }

    async def _restore_file(self, conn_id: str, config: ConnectionConfig) -> None:
        import os
        db_path = config.database
        if not os.path.exists(db_path):
            logger.warning("File DB not found: %s", db_path)
            self._connections[conn_id] = {
                "config": config, "status": "disconnected", "type": "file",
            }
            return

        aiosqlite_url = f"sqlite+aiosqlite:///{db_path}"
        engine = create_async_engine(aiosqlite_url)
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            status = "connected"
        except Exception:
            status = "disconnected"

        self._connections[conn_id] = {
            "config": config, "engine": engine,
            "status": status, "type": "file",
        }

    # ── Normal connection lifecycle ───────────────────────────────
    async def add_connection(self, config: ConnectionConfig) -> ConnectionInfo:
        """Add a new database connection. Routes to SQL or Cosmos based on connector_type."""

        if config.connector_type == "cosmosdb":
            return await self._add_cosmos_connection(config)
        if config.connector_type == "powerbi":
            return await self._add_powerbi_connection(config)
        if config.connector_type == "file":
            # File connections are created via the /upload endpoint
            return ConnectionInfo(
                id="", name=config.name, connector_type="file",
                host="local", database=config.database, status="disconnected",
            )

        return await self._add_sql_connection(config)

    async def _add_sql_connection(self, config: ConnectionConfig) -> ConnectionInfo:
        """Add a PostgreSQL / MySQL / SQL Server connection."""
        conn_id = uuid.uuid4().hex[:12]
        url = (
            f"postgresql+asyncpg://{config.user}:{config.password}"
            f"@{config.host}:{config.port}/{config.database}"
        )
        engine = create_async_engine(url, pool_size=5, max_overflow=2)

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            status = "connected"
        except Exception:
            status = "disconnected"

        self._connections[conn_id] = {
            "config": config,
            "engine": engine,
            "status": status,
            "type": config.connector_type,
        }

        # Persist to store
        from app.db.connection_store import save_connection
        save_connection(conn_id, config, config.connector_type)

        return ConnectionInfo(
            id=conn_id,
            name=config.name,
            connector_type=config.connector_type,
            host=config.host,
            database=config.database,
            status=status,
        )

    async def _add_cosmos_connection(self, config: ConnectionConfig) -> ConnectionInfo:
        """Add a Cosmos DB connection."""
        from app.db.cosmos_manager import cosmos_manager
        info = await cosmos_manager.add_connection(config)
        # Also register it here so get_connection_type works
        self._connections[info.id] = {
            "config": config,
            "status": info.status,
            "type": "cosmosdb",
        }

        # Persist to store
        from app.db.connection_store import save_connection
        save_connection(info.id, config, "cosmosdb")

        return info

    async def _add_powerbi_connection(self, config: ConnectionConfig) -> ConnectionInfo:
        """Add a Power BI connection."""
        from app.db.powerbi_manager import powerbi_manager
        info = await powerbi_manager.add_connection(config)
        self._connections[info.id] = {
            "config": config,
            "status": info.status,
            "type": "powerbi",
        }

        from app.db.connection_store import save_connection
        save_connection(info.id, config, "powerbi")

        return info

    def get_engine(self, connection_id: str) -> AsyncEngine | None:
        conn = self._connections.get(connection_id)
        if conn and conn.get("type") not in ("cosmosdb", "powerbi"):
            return conn.get("engine")
        return None

    def get_file_engine(self, connection_id: str) -> AsyncEngine | None:
        conn = self._connections.get(connection_id)
        if conn and conn.get("type") == "file":
            return conn.get("engine")
        return None

    def get_connection_type(self, connection_id: str) -> str | None:
        conn = self._connections.get(connection_id)
        return conn["type"] if conn else None

    def has_connection(self, connection_id: str) -> bool:
        return connection_id in self._connections

    def list_connections(self) -> list[ConnectionInfo]:
        """Return list of ConnectionInfo (without passwords)."""
        result: list[ConnectionInfo] = []
        for conn_id, entry in self._connections.items():
            cfg = entry["config"]
            if entry["type"] == "cosmosdb":
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
            elif entry["type"] == "powerbi":
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
            elif entry["type"] == "file":
                result.append(
                    ConnectionInfo(
                        id=conn_id,
                        name=cfg.name,
                        connector_type="file",
                        host="local",
                        database=cfg.database,
                        status=entry["status"],
                    )
                )
            else:
                result.append(
                    ConnectionInfo(
                        id=conn_id,
                        name=cfg.name,
                        connector_type=cfg.connector_type,
                        host=cfg.host,
                        database=cfg.database,
                        status=entry["status"],
                    )
                )
        return result

    async def test_connection(self, connection_id: str) -> bool:
        entry = self._connections.get(connection_id)
        if entry is None:
            return False

        if entry["type"] == "cosmosdb":
            from app.db.cosmos_manager import cosmos_manager
            return await cosmos_manager.test_connection(connection_id)

        if entry["type"] == "powerbi":
            from app.db.powerbi_manager import powerbi_manager
            return await powerbi_manager.test_connection(connection_id)

        engine: AsyncEngine = entry["engine"]
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            entry["status"] = "connected"
            return True
        except Exception:
            entry["status"] = "disconnected"
            return False

    async def remove_connection(self, connection_id: str) -> None:
        entry = self._connections.pop(connection_id, None)
        if entry is None:
            return
        if entry["type"] == "cosmosdb":
            from app.db.cosmos_manager import cosmos_manager
            await cosmos_manager.remove_connection(connection_id)
        elif entry["type"] == "powerbi":
            from app.db.powerbi_manager import powerbi_manager
            await powerbi_manager.remove_connection(connection_id)
        elif entry.get("engine"):
            await entry["engine"].dispose()

        # Remove from persistent store
        from app.db.connection_store import remove_connection as store_remove
        store_remove(connection_id)

    async def close_all(self) -> None:
        for entry in self._connections.values():
            if entry.get("engine"):
                await entry["engine"].dispose()
        self._connections.clear()


# Singleton instance
connection_manager = ConnectionManager()
