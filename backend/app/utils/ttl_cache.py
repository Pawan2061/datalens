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

    def get(self, key: str) -> T | None:
        self._purge_expired()
        entry = self._entries.get(key)
        if entry is None:
            return None
        return copy.deepcopy(entry.value)

    def set(self, key: str, value: T) -> None:
        self._purge_expired()
        if key not in self._entries and len(self._entries) >= self._max_size:
            oldest_key = min(self._entries, key=lambda item: self._entries[item].created_at)
            self._entries.pop(oldest_key, None)
        self._entries[key] = _Entry(value=copy.deepcopy(value), created_at=time.monotonic())

    def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            key for key, entry in self._entries.items()
            if (now - entry.created_at) > self._ttl_seconds
        ]
        for key in expired:
            self._entries.pop(key, None)
