from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.config import settings
from app.db.connection_manager import connection_manager


@dataclass
class _CacheEntry:
    formatted_schema: str
    created_at: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > settings.schema_cache_ttl


class SchemaCache:
    """In-memory schema cache, keyed by connection_id, with TTL."""

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}

    async def get(self, connection_id: str) -> str:
        """Return formatted schema string. Fetches from DB on cache miss/expiry."""
        entry = self._cache.get(connection_id)
        if entry and not entry.is_expired():
            return entry.formatted_schema

        conn_type = connection_manager.get_connection_type(connection_id)

        if conn_type == "cosmosdb":
            from app.db.cosmos_manager import cosmos_manager
            formatted = cosmos_manager.format_schema_for_llm(connection_id)
        elif conn_type == "powerbi":
            from app.db.powerbi_manager import powerbi_manager
            formatted = powerbi_manager.format_schema_for_llm(connection_id)
        else:
            from app.db.schema_inspector import format_schema_for_llm, inspect_schema
            engine = connection_manager.get_engine(connection_id)
            if engine is None:
                raise ValueError(f"Connection {connection_id} not found")
            schema = await inspect_schema(engine)
            formatted = format_schema_for_llm(schema)

        self._cache[connection_id] = _CacheEntry(formatted_schema=formatted)
        return formatted

    def invalidate(self, connection_id: str) -> None:
        """Bust the cache for a connection."""
        self._cache.pop(connection_id, None)

    def clear(self) -> None:
        """Clear the entire cache."""
        self._cache.clear()


# Singleton
schema_cache = SchemaCache()
