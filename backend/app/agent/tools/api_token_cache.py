"""Async-safe token cache for two-step API tools.

Stores short-lived auth tokens keyed by (workspace_id, tool_id) and serializes
concurrent fetches through per-key locks so that a burst of tool calls with an
expired token triggers exactly one refresh round-trip.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass
class _TokenEntry:
    token: str
    expires_at: float  # monotonic timestamp


_entries: dict[tuple[str, str], _TokenEntry] = {}
_locks: dict[tuple[str, str], asyncio.Lock] = {}
_locks_guard = asyncio.Lock()
_hits = 0
_misses = 0
_sets = 0
_invalidations = 0
_expiries = 0


def _key(workspace_id: str, tool_id: str) -> tuple[str, str]:
    return (workspace_id or "", tool_id or "")


async def _get_lock(workspace_id: str, tool_id: str) -> asyncio.Lock:
    key = _key(workspace_id, tool_id)
    lock = _locks.get(key)
    if lock is not None:
        return lock
    async with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock


def get_cached_token(workspace_id: str, tool_id: str) -> str | None:
    """Return a non-expired cached token, or None."""
    global _hits, _misses, _expiries
    entry = _entries.get(_key(workspace_id, tool_id))
    if entry is None:
        _misses += 1
        return None
    if time.monotonic() >= entry.expires_at:
        _entries.pop(_key(workspace_id, tool_id), None)
        _expiries += 1
        _misses += 1
        return None
    _hits += 1
    return entry.token


def set_cached_token(
    workspace_id: str, tool_id: str, token: str, ttl_seconds: float
) -> None:
    """Store a freshly fetched token with the given TTL."""
    global _sets
    if not token:
        return
    _entries[_key(workspace_id, tool_id)] = _TokenEntry(
        token=token,
        expires_at=time.monotonic() + max(1.0, float(ttl_seconds)),
    )
    _sets += 1


def invalidate_token(workspace_id: str, tool_id: str) -> None:
    """Drop the cached token (e.g. after upstream rejection)."""
    global _invalidations
    if _entries.pop(_key(workspace_id, tool_id), None) is not None:
        _invalidations += 1


async def with_token_lock(workspace_id: str, tool_id: str):
    """Return an awaitable context manager that serializes token refreshes
    for a single (workspace, tool) pair."""
    lock = await _get_lock(workspace_id, tool_id)
    return lock


def stats() -> dict:
    total_lookups = _hits + _misses
    hit_rate = _hits / total_lookups if total_lookups else 0.0
    return {
        "entries": len(_entries),
        "locks": len(_locks),
        "hits": _hits,
        "misses": _misses,
        "hit_rate": round(hit_rate, 4),
        "sets": _sets,
        "invalidations": _invalidations,
        "expiries": _expiries,
    }
