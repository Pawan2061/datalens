"""Background loop that keeps Anthropic's 5-min ephemeral prompt cache hot
for recently-active workspaces.

Without warming, any idle gap >5 min forces the next real request to pay
`cache_creation` (1.25x input) instead of `cache_read` (0.1x) — a 12.5x swing
on the prefix tokens. This task reconstructs the byte-identical static prefix
that real requests send and pings Anthropic with `max_tokens=1`, no tools,
and no conversation history. Any cache hit or write shows up in usage logs
under the warmer's synthetic user_id, so cost is observable.

Safety:
- Disabled by default (settings.anthropic_cache_warming_enabled).
- Runs only when llm_provider == "anthropic" and prompt caching is on.
- Semaphore bounds concurrent pings so we can't saturate Anthropic's rate limit.
- All exceptions are caught and logged — the task never crashes the process.
- Activity is tracked fire-and-forget from the chat handler; if the tracker
  is empty (no recent traffic), the loop sleeps and does nothing.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.active_workspaces import WarmTarget, active_targets
from app.agent.api_tool_cache import (
    get_cached_workspace_api_tools,
    set_cached_workspace_api_tools,
)
from app.agent.prompts import build_system_prompt
from app.agent.schema_cache import schema_cache
from app.agent.tools.api_tool_factory import describe_api_tools_for_prompt
from app.config import settings
from app.db.connection_manager import connection_manager

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


# Connector labels mirror graph.py so warmer's prefix matches byte-for-byte.
_CONNECTOR_LABELS = {
    "cosmosdb": "Azure Cosmos DB",
    "powerbi": "Power BI",
}


@lru_cache(maxsize=1)
def _warmer_llm():
    """Dedicated Anthropic client with max_tokens=1. Singleton."""
    from app.llm.openai_llm import _patch_anthropic_env
    from langchain_anthropic import ChatAnthropic

    _patch_anthropic_env()
    key = settings.anthropic_foundry_key or settings.anthropic_api_key
    return ChatAnthropic(
        model=settings.anthropic_worker_model,
        api_key=key,
        base_url=settings.anthropic_foundry_url or None,
        temperature=0,
        max_tokens=1,
    )


async def _load_api_tools_for(workspace_id: str) -> list[dict]:
    """Mirror of graph.py's inline loader — hits the 60s cache when possible."""
    cached = get_cached_workspace_api_tools(workspace_id)
    if cached is not None:
        return cached
    try:
        from app.db.insight_db import insight_db
        if not insight_db.is_ready:
            return []
        container = insight_db.container("workspaces")
        items = await asyncio.to_thread(
            lambda: list(container.query_items(
                query="SELECT c.api_tools FROM c WHERE c.id = @wid",
                parameters=[{"name": "@wid", "value": workspace_id}],
                partition_key=workspace_id,
            ))
        )
        tools = items[0]["api_tools"] if items and items[0].get("api_tools") else []
        set_cached_workspace_api_tools(workspace_id, tools)
        return tools
    except Exception:
        return []


async def _build_prefix_for(target: WarmTarget) -> str | None:
    """Reconstruct exactly the static_prefix that a real request would send.

    Returns None if the prefix can't be built (e.g. connection gone) or is
    below the min-tokens threshold — in either case there's nothing useful
    to warm.
    """
    conn_type = connection_manager.get_connection_type(target.connection_id) or "postgresql"
    connector_label = _CONNECTOR_LABELS.get(conn_type, "PostgreSQL")

    # Parallel loads, same order as graph.py
    from app.agent.profiler import load_profile

    profile_doc, api_tool_configs, schema_text = await asyncio.gather(
        load_profile(target.workspace_id, target.connection_id),
        _load_api_tools_for(target.workspace_id),
        schema_cache.get(target.connection_id),
    )

    profile_text = ""
    if profile_doc and profile_doc.status == "ready" and profile_doc.profile_text:
        profile_text = profile_doc.profile_text
        schema_text = ""

    system_prompt = build_system_prompt(
        schema=schema_text,
        connection_id=target.connection_id,
        selected_tables=None,  # warmer targets the most common variant
        analysis_mode=target.analysis_mode,
        connector_type=connector_label,
        workspace_profile=profile_text,
    )

    if api_tool_configs:
        # Use empty scope — matches admin-mode requests. Users on customer
        # scope get a different prefix; warming the admin variant still helps
        # because admin requests are the common case during config/testing.
        system_prompt += describe_api_tools_for_prompt(
            api_tool_configs,
            customer_scope="",
            customer_scope_name="",
        )

    if (len(system_prompt) // 4) < settings.anthropic_prompt_cache_min_tokens:
        return None
    return system_prompt


async def _warm_one(target: WarmTarget, sem: asyncio.Semaphore) -> None:
    async with sem:
        try:
            prefix = await _build_prefix_for(target)
            if not prefix:
                return
            llm = _warmer_llm()
            messages = [
                SystemMessage(content=[
                    {
                        "type": "text",
                        "text": prefix,
                        "cache_control": {"type": "ephemeral"},
                    },
                ]),
                # A single-byte user turn is enough to make the API accept
                # the system prefix; max_tokens=1 caps output cost.
                HumanMessage(content="."),
            ]
            resp = await llm.ainvoke(messages)
            # Observability: log cache read/write so operators can see the
            # warmer is actually hitting the same cache entry real requests use.
            um = getattr(resp, "usage_metadata", None) or {}
            details = um.get("input_token_details") or {}
            # langchain-anthropic >=1.4 zeroes `cache_creation` and reports
            # writes under `ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`
            # when the API returns a TTL breakdown. Sum all three.
            cache_create = (
                (details.get("cache_creation") or 0)
                + (details.get("ephemeral_5m_input_tokens") or 0)
                + (details.get("ephemeral_1h_input_tokens") or 0)
            )
            logger.info(
                "[cache-warmer] ws=%s conn=%s mode=%s read=%d create=%d input=%d",
                target.workspace_id,
                target.connection_id,
                target.analysis_mode,
                details.get("cache_read", 0) or 0,
                cache_create,
                um.get("input_tokens", 0),
            )
        except Exception as exc:
            logger.warning(
                "[cache-warmer] failed ws=%s conn=%s: %s",
                target.workspace_id,
                target.connection_id,
                exc,
            )


async def _loop() -> None:
    interval = max(30, int(settings.anthropic_cache_warming_interval_seconds))
    window = max(interval * 2, int(settings.anthropic_cache_warming_active_window_seconds))
    max_concurrent = max(1, int(settings.anthropic_cache_warming_max_concurrent))
    sem = asyncio.Semaphore(max_concurrent)

    logger.info(
        "[cache-warmer] started interval=%ss window=%ss max_concurrent=%d",
        interval, window, max_concurrent,
    )
    assert _stop_event is not None
    try:
        while not _stop_event.is_set():
            try:
                targets = active_targets(window)
                if targets:
                    await asyncio.gather(
                        *(_warm_one(t, sem) for t in targets),
                        return_exceptions=True,
                    )
            except Exception as exc:
                logger.warning("[cache-warmer] tick failed: %s", exc)

            try:
                await asyncio.wait_for(_stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass  # next tick
    finally:
        logger.info("[cache-warmer] stopped")


def start() -> None:
    """Start the warmer background task. No-op if disabled or already running."""
    global _task, _stop_event
    if not settings.anthropic_cache_warming_enabled:
        return
    if settings.llm_provider != "anthropic" or not settings.anthropic_prompt_caching:
        logger.info("[cache-warmer] skipped — requires llm_provider=anthropic with prompt caching on")
        return
    if _task and not _task.done():
        return
    _stop_event = asyncio.Event()
    _task = asyncio.create_task(_loop(), name="cache-warmer")


async def stop() -> None:
    """Signal the warmer to stop and wait briefly for it to finish."""
    global _task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
    _task = None
    _stop_event = None
