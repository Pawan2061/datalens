from __future__ import annotations

from datetime import date, datetime, timezone


FALLBACK_PRICING = {"input": 1.0, "output": 5.0}

_STATIC_PRICING: tuple[tuple[str, dict[str, float]], ...] = (
    ("claude-sonnet-4-6", {"input": 3.0, "output": 15.0}),
    ("claude-sonnet-4-5", {"input": 3.0, "output": 15.0}),
    ("claude-sonnet-4-20250514", {"input": 3.0, "output": 15.0}),
    ("claude-sonnet-4", {"input": 3.0, "output": 15.0}),
    ("claude-opus-4-8", {"input": 5.0, "output": 25.0}),
    ("claude-opus-4-7", {"input": 5.0, "output": 25.0}),
    ("claude-opus-4-6", {"input": 5.0, "output": 25.0}),
    ("claude-opus-4-5", {"input": 5.0, "output": 25.0}),
    ("claude-opus-4-1", {"input": 15.0, "output": 75.0}),
    ("claude-opus-4-0", {"input": 15.0, "output": 75.0}),
    ("claude-opus-4", {"input": 15.0, "output": 75.0}),
    ("claude-haiku-4-5", {"input": 1.0, "output": 5.0}),
    ("claude-haiku-3-5", {"input": 0.8, "output": 4.0}),
    ("gpt-4o", {"input": 2.5, "output": 10.0}),
    ("gpt-4.1-mini", {"input": 0.4, "output": 1.6}),
    ("gemini-2.0-flash", {"input": 0.0, "output": 0.0}),
    ("gemini-2.5-flash", {"input": 0.0, "output": 0.0}),
    ("gemini", {"input": 0.0, "output": 0.0}),
)


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def resolve_model_pricing(
    model_name: str,
    *,
    as_of: date | None = None,
) -> tuple[dict[str, float], bool]:
    """Return per-1M-token pricing and whether the model matched explicitly."""
    model_lower = (model_name or "").lower()
    effective_date = as_of or _today_utc()

    if "claude-sonnet-5" in model_lower:
        if effective_date < date(2026, 9, 1):
            return {"input": 2.0, "output": 10.0}, True
        return {"input": 3.0, "output": 15.0}, True

    for key, pricing in _STATIC_PRICING:
        if key in model_lower:
            return pricing, True
    return FALLBACK_PRICING, False


def estimate_token_cost_usd(
    input_tokens: int,
    output_tokens: int,
    model_name: str,
    *,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    as_of: date | None = None,
) -> float:
    """Estimate request cost with Anthropic-style cache token buckets."""
    pricing, _matched = resolve_model_pricing(model_name, as_of=as_of)
    fresh_input = max(input_tokens - cache_read_tokens - cache_creation_tokens, 0)
    cost = (
        (fresh_input * pricing["input"] / 1_000_000)
        + (output_tokens * pricing["output"] / 1_000_000)
        + (cache_creation_tokens * pricing["input"] * 1.25 / 1_000_000)
        + (cache_read_tokens * pricing["input"] * 0.10 / 1_000_000)
    )
    return round(cost, 6)
