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
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._invalidations = 0
        self._expiries = 0

    async def get(self, connection_id: str) -> str:
        """Return formatted schema string. Fetches from DB on cache miss/expiry."""
        entry = self._cache.get(connection_id)
        if entry and not entry.is_expired():
            self._hits += 1
            return entry.formatted_schema
        if entry:
            self._expiries += 1
        self._misses += 1

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
            schema = await inspect_schema(engine, conn_type)
            formatted = format_schema_for_llm(schema)

        self._cache[connection_id] = _CacheEntry(formatted_schema=formatted)
        self._sets += 1
        return formatted

    def invalidate(self, connection_id: str) -> None:
        """Bust the cache for a connection."""
        if self._cache.pop(connection_id, None) is not None:
            self._invalidations += 1

    def clear(self) -> None:
        """Clear the entire cache."""
        self._invalidations += len(self._cache)
        self._cache.clear()

    def stats(self) -> dict:
        total_lookups = self._hits + self._misses
        hit_rate = self._hits / total_lookups if total_lookups else 0.0
        return {
            "entries": len(self._cache),
            "ttl_seconds": settings.schema_cache_ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "sets": self._sets,
            "invalidations": self._invalidations,
            "expiries": self._expiries,
        }


# Singleton
schema_cache = SchemaCache()
