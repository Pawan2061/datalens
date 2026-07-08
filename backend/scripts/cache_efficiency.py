"""Read-only cache-efficiency report from persisted usage/analytics tables.

Usage:
    DATABASE_URL=postgresql://... python -m scripts.cache_efficiency --days 7
"""
from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

import psycopg
import psycopg.rows

from app.api.routes.admin import _cache_efficiency_summary


def _normalize_database_url(raw: str) -> str:
    if raw.startswith("postgresql+psycopg://"):
        return "postgresql://" + raw.removeprefix("postgresql+psycopg://")
    return raw


def _refuse_localhost(url: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
        raise SystemExit(
            "Refusing to run against localhost by default. Use the app DB URL "
            "for production/staging audits."
        )


def _fetch_rows(conn: psycopg.Connection, table: str) -> list[dict]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY timestamp DESC")
        return [dict(row) for row in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize DataLens cache efficiency.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window, 1-90 days.")
    parser.add_argument("--allow-localhost", action="store_true")
    args = parser.parse_args()

    raw_url = os.environ.get("DATABASE_URL", "")
    if not raw_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2

    db_url = _normalize_database_url(raw_url)
    if not args.allow_localhost:
        _refuse_localhost(db_url)

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
        usage_logs = _fetch_rows(conn, "usage_logs")
        analytics_events = _fetch_rows(conn, "analytics_events")
        with conn.cursor() as cur:
            cur.execute("ROLLBACK")

    summary = _cache_efficiency_summary(
        usage_logs,
        analytics_events,
        days=max(1, min(args.days, 90)),
    )

    response_cache = summary["response_cache"]
    prompt_cache = summary["anthropic_prompt_cache"]
    llm_usage = summary["llm_usage"]

    print(f"Window: {summary['window_days']} day(s)")
    print(f"Analytics events: {summary['analytics_events']}")
    print(f"Usage rows: {summary['usage_rows']}")
    print(
        "Response cache: "
        f"{response_cache['hits']} hits, "
        f"{response_cache['hit_rate']:.2%} hit rate, "
        f"${response_cache['estimated_cost_avoided_usd']:.4f} estimated avoided"
    )
    print(
        "Anthropic prompt cache: "
        f"{prompt_cache['cache_read_tokens']:,} read tokens, "
        f"{prompt_cache['cache_creation_tokens']:,} write tokens, "
        f"${prompt_cache['net_estimated_savings_usd']:.4f} net estimated savings"
    )
    print(f"LLM cost: ${llm_usage['cost_usd']:.4f}")
    print(f"Model distribution: {llm_usage['model_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
