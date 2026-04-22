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
    entry = _entries.get(_key(workspace_id, tool_id))
    if entry is None:
        return None
    if time.monotonic() >= entry.expires_at:
        return None
    return entry.token


def set_cached_token(
    workspace_id: str, tool_id: str, token: str, ttl_seconds: float
) -> None:
    """Store a freshly fetched token with the given TTL."""
    if not token:
        return
    _entries[_key(workspace_id, tool_id)] = _TokenEntry(
        token=token,
        expires_at=time.monotonic() + max(1.0, float(ttl_seconds)),
    )


def invalidate_token(workspace_id: str, tool_id: str) -> None:
    """Drop the cached token (e.g. after upstream rejection)."""
    _entries.pop(_key(workspace_id, tool_id), None)


async def with_token_lock(workspace_id: str, tool_id: str):
    """Return an awaitable context manager that serializes token refreshes
    for a single (workspace, tool) pair."""
    lock = await _get_lock(workspace_id, tool_id)
    return lock
