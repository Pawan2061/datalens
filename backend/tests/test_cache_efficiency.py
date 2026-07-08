from __future__ import annotations

import time
from datetime import datetime, timezone

from app.agent.active_workspaces import active_targets, record
from app.agent.quick_responses import ResponseCache
from app.api.routes.admin import _cache_efficiency_summary
from app.utils.ttl_cache import TTLCache


def test_ttl_cache_stats_track_hits_misses_evictions_and_expiry():
    cache: TTLCache[dict] = TTLCache(ttl_seconds=0.01, max_size=1)

    assert cache.get("missing") is None
    cache.set("a", {"value": 1})
    assert cache.get("a") == {"value": 1}
    cache.set("b", {"value": 2})
    assert cache.get("a") is None
    time.sleep(0.02)
    assert cache.get("b") is None

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 3
    assert stats["sets"] == 2
    assert stats["evictions"] == 1
    assert stats["expiries"] == 1


def test_response_cache_stats_and_scope_separation():
    cache = ResponseCache(max_size=2, ttl_seconds=60)
    response = {
        "execution_metadata": {"total_rows": 1},
        "summary": {"title": "ok"},
    }

    cache.put("Show sales", "conn", response, customer_scope="A")
    assert cache.get("show sales", "conn", customer_scope="A") == response
    assert cache.get("show sales", "conn", customer_scope="B") is None

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 0.5
    assert stats["puts"] == 1


def test_cache_efficiency_summary_estimates_response_and_prompt_cache_savings():
    now = datetime(2026, 7, 8, tzinfo=timezone.utc)
    usage_logs = [
        {
            "timestamp": now.isoformat(),
            "model_name": "claude-haiku-4-5",
            "input_tokens": 10_000,
            "output_tokens": 1_000,
            "cache_read_tokens": 4_000,
            "cache_creation_tokens": 1_000,
            "cost_usd": 0.012,
        }
    ]
    analytics_events = [
        {"timestamp": now.isoformat(), "cached": False, "cost_usd": 0.012},
        {"timestamp": now.isoformat(), "cached": True, "cost_usd": 0.0},
    ]

    summary = _cache_efficiency_summary(
        usage_logs,
        analytics_events,
        days=7,
        now=now,
    )

    assert summary["response_cache"]["hits"] == 1
    assert summary["response_cache"]["hit_rate"] == 0.5
    assert summary["response_cache"]["estimated_cost_avoided_usd"] == 0.012
    assert summary["anthropic_prompt_cache"]["cache_read_tokens"] == 4_000
    assert summary["anthropic_prompt_cache"]["cache_creation_tokens"] == 1_000
    assert summary["anthropic_prompt_cache"]["net_estimated_savings_usd"] == 0.00335


def test_active_workspace_tracker_keeps_customer_scope_for_warmer():
    record("ws-cache-test", "conn-cache-test", "quick", "C001", "Acme")
    targets = active_targets(60)
    target = next(t for t in targets if t.workspace_id == "ws-cache-test")

    assert target.customer_scope == "C001"
    assert target.customer_scope_name == "Acme"
