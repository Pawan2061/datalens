"""In-memory per-user burst rate limiter for the chat endpoint.

There is no Redis in this stack, so this mirrors the existing in-process
caching pattern (see app/utils/ttl_cache.py). A sliding window of recent
request timestamps is kept per user_id and pruned on each check.

CAVEAT: state is per-process. On multi-instance deployments (e.g. Cloud Run
with >1 instance) the effective limit is roughly limit x instances. That is
acceptable here — the goal is to stop runaway loops / scripted abuse and the
associated LLM cost, not to enforce a precise global quota. The DB-backed
quota in app/auth/quota.py handles exact daily/monthly limits.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from app.config import settings

# user_id -> deque[float monotonic timestamps], newest appended on the right.
_hits: dict[str, deque[float]] = defaultdict(deque)

_MINUTE = 60.0
_HOUR = 3600.0


class RateLimitResult:
    """Outcome of a rate-limit check. retry_after is seconds (for the header)."""

    __slots__ = ("allowed", "reason", "retry_after")

    def __init__(self, allowed: bool, reason: str = "", retry_after: int = 0):
        self.allowed = allowed
        self.reason = reason
        self.retry_after = retry_after


def check_rate_limit(user_id: str) -> RateLimitResult:
    """Record an attempt for `user_id` and decide whether it is allowed.

    Runs synchronously with no `await`, so within the single-threaded asyncio
    event loop the prune/count/append sequence is atomic — no lock needed.
    """
    now = time.monotonic()
    per_minute = settings.rate_limit_per_minute
    per_hour = settings.rate_limit_per_hour

    hits = _hits[user_id]

    # Prune anything older than the largest window so memory stays bounded.
    cutoff = now - _HOUR
    while hits and hits[0] < cutoff:
        hits.popleft()

    # Per-minute window.
    if per_minute > 0:
        minute_count = sum(1 for t in hits if t >= now - _MINUTE)
        if minute_count >= per_minute:
            return RateLimitResult(
                allowed=False,
                reason=(
                    "You're sending requests a little too quickly. Please wait "
                    "about a minute and try again — this helps us keep DataLens "
                    "fast and reliable for everyone. Thank you for understanding!"
                ),
                retry_after=60,
            )

    # Per-hour window.
    if per_hour > 0 and len(hits) >= per_hour:
        return RateLimitResult(
            allowed=False,
            reason=(
                "You've reached the hourly request limit. Please take a short "
                "break and try again a little later — we appreciate your patience "
                "and your understanding in helping us keep DataLens reliable for "
                "everyone."
            ),
            retry_after=3600,
        )

    hits.append(now)
    return RateLimitResult(allowed=True)
