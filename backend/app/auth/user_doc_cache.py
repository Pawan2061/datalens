from __future__ import annotations

from app.utils.ttl_cache import TTLCache


_user_doc_cache: TTLCache[dict] = TTLCache(ttl_seconds=10, max_size=1024)


def get_cached_user_doc(user_id: str) -> dict | None:
    return _user_doc_cache.get(user_id)


def set_cached_user_doc(user_id: str, user_doc: dict) -> None:
    _user_doc_cache.set(user_id, user_doc)


def invalidate_cached_user_doc(user_id: str) -> None:
    _user_doc_cache.delete(user_id)
