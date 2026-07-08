from __future__ import annotations

import copy
import time
from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    created_at: float


class TTLCache(Generic[T]):
    """Small in-memory TTL cache for hot-path metadata and query results."""

    def __init__(self, ttl_seconds: float, max_size: int = 256):
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._entries: dict[str, _Entry[T]] = {}
        self._hits = 0
        self._misses = 0
        self._sets = 0
        self._evictions = 0
        self._expiries = 0
        self._deletes = 0

    def get(self, key: str) -> T | None:
        self._purge_expired()
        entry = self._entries.get(key)
        if entry is None:
            self._misses += 1
            return None
        self._hits += 1
        return copy.deepcopy(entry.value)

    def set(self, key: str, value: T) -> None:
        self._purge_expired()
        if key not in self._entries and len(self._entries) >= self._max_size:
            oldest_key = min(self._entries, key=lambda item: self._entries[item].created_at)
            self._entries.pop(oldest_key, None)
            self._evictions += 1
        self._entries[key] = _Entry(value=copy.deepcopy(value), created_at=time.monotonic())
        self._sets += 1

    def delete(self, key: str) -> None:
        if self._entries.pop(key, None) is not None:
            self._deletes += 1

    def stats(self) -> dict:
        total_lookups = self._hits + self._misses
        hit_rate = self._hits / total_lookups if total_lookups else 0.0
        return {
            "entries": len(self._entries),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl_seconds,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "sets": self._sets,
            "evictions": self._evictions,
            "expiries": self._expiries,
            "deletes": self._deletes,
        }

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            key for key, entry in self._entries.items()
            if (now - entry.created_at) > self._ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
        self._expiries += len(expired)
