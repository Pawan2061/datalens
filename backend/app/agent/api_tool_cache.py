from __future__ import annotations

from app.utils.ttl_cache import TTLCache


_workspace_api_tools_cache: TTLCache[list[dict]] = TTLCache(ttl_seconds=60, max_size=512)


def get_cached_workspace_api_tools(workspace_id: str) -> list[dict] | None:
    return _workspace_api_tools_cache.get(workspace_id)


def set_cached_workspace_api_tools(workspace_id: str, tools: list[dict]) -> None:
    _workspace_api_tools_cache.set(workspace_id, tools)


def invalidate_workspace_api_tools_cache(workspace_id: str) -> None:
    _workspace_api_tools_cache.delete(workspace_id)
