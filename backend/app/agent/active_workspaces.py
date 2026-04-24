"""Fire-and-forget tracker of recently-active (workspace_id, connection_id, mode)
tuples. The cache warmer polls this to decide what to keep hot.

Writes are lock-free dict assignments (single-statement; CPython GIL makes this
safe for our usage) so the chat hot path sees zero latency overhead. Reads
happen only in the warmer's background task.
"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True)
class WarmTarget:
    workspace_id: str
    connection_id: str
    analysis_mode: str


# key -> last-activity monotonic timestamp
_activity: dict[WarmTarget, float] = {}


def record(
    workspace_id: str,
    connection_id: str,
    analysis_mode: str,
) -> None:
    """Note that a real request just started for this tuple. No I/O, no await."""
    if not (workspace_id and connection_id):
        return
    _activity[WarmTarget(workspace_id, connection_id, analysis_mode or "quick")] = time.monotonic()


def active_targets(window_seconds: float) -> list[WarmTarget]:
    """Return targets active within the window. Also prunes expired entries."""
    cutoff = time.monotonic() - window_seconds
    stale = [k for k, ts in _activity.items() if ts < cutoff]
    for k in stale:
        _activity.pop(k, None)
    return list(_activity.keys())
