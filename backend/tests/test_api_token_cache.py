"""Tests for the token cache."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.agent.tools import api_token_cache


@pytest.fixture(autouse=True)
def _reset():
    api_token_cache._entries.clear()
    api_token_cache._locks.clear()
    yield
    api_token_cache._entries.clear()
    api_token_cache._locks.clear()


def test_set_and_get_roundtrip():
    api_token_cache.set_cached_token("ws", "t", "TOK", ttl_seconds=10)
    assert api_token_cache.get_cached_token("ws", "t") == "TOK"


def test_expired_token_returns_none():
    api_token_cache.set_cached_token("ws", "t", "TOK", ttl_seconds=1)
    # force expire by rewinding the stored entry
    entry = api_token_cache._entries[("ws", "t")]
    entry.expires_at = time.monotonic() - 0.01
    assert api_token_cache.get_cached_token("ws", "t") is None


def test_invalidate_removes_entry():
    api_token_cache.set_cached_token("ws", "t", "TOK", ttl_seconds=60)
    api_token_cache.invalidate_token("ws", "t")
    assert api_token_cache.get_cached_token("ws", "t") is None


@pytest.mark.asyncio
async def test_lock_is_reentrant_per_key():
    lock_a1 = await api_token_cache.with_token_lock("ws", "t")
    lock_a2 = await api_token_cache.with_token_lock("ws", "t")
    assert lock_a1 is lock_a2

    lock_b = await api_token_cache.with_token_lock("ws", "other")
    assert lock_b is not lock_a1


@pytest.mark.asyncio
async def test_empty_token_not_stored():
    api_token_cache.set_cached_token("ws", "t", "", ttl_seconds=60)
    assert api_token_cache.get_cached_token("ws", "t") is None
