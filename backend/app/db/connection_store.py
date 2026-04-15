"""Cosmos DB–based persistence for database connection configs.

Saves connection configs to the DataLens 'connections' container
so they survive server restarts. On startup, all saved connections
are re-established automatically.
"""

from __future__ import annotations

import logging

from app.schemas.connection import ConnectionConfig

logger = logging.getLogger(__name__)


def _get_container():
    """Get the 'connections' container from InsightDB, or None if not ready."""
    from app.db.insight_db import insight_db
    if not insight_db.is_ready:
        return None
    try:
        return insight_db.container("connections")
    except (RuntimeError, KeyError):
        return None


def load_all() -> list[dict]:
    """Load all saved connection configs from Cosmos DB.

    Returns:
        list of dicts, each with keys: id, config, connector_type
    """
    container = _get_container()
    if container is None:
        logger.info("InsightDB not ready — skipping connection store load")
        return []

    try:
        items = list(container.read_all_items())
        return items
    except Exception as e:
        logger.warning("Failed to load connections from Cosmos DB: %s", e)
        return []


def save_connection(connection_id: str, config: ConnectionConfig, conn_type: str) -> None:
    """Persist a connection config to Cosmos DB."""
    container = _get_container()
    if container is None:
        logger.info("InsightDB not ready — connection %s not persisted", connection_id)
        return

    doc = {
        "id": connection_id,
        "connector_type": conn_type,
        "config": config.model_dump(by_alias=True),
    }

    try:
        container.upsert_item(doc)
        logger.info("Saved connection %s to Cosmos DB", connection_id)
    except Exception as e:
        logger.warning("Failed to save connection %s: %s", connection_id, e)


def remove_connection(connection_id: str) -> None:
    """Remove a connection config from Cosmos DB."""
    container = _get_container()
    if container is None:
        return

    try:
        items = list(container.query_items(
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": connection_id}],
            enable_cross_partition_query=True,
        ))
        if items:
            container.delete_item(item=items[0]["id"], partition_key=items[0]["connector_type"])
            logger.info("Removed connection %s from Cosmos DB", connection_id)
    except Exception as e:
        logger.warning("Failed to remove connection %s: %s", connection_id, e)
