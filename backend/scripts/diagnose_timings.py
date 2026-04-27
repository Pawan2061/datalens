"""Print one line per analytics_event in the last hour so you can see
which rows have duration_ms / step_timings populated and which don't.

Useful for confirming whether ``duration_ms = 0`` rows are pre-restart
legacy data or a live bug.

Run from ``backend/``:

    ./venv/bin/python -m scripts.diagnose_timings           # last hour
    ./venv/bin/python -m scripts.diagnose_timings --hours 6 # custom window
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.db.insight_db import insight_db  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hours", type=float, default=1.0)
    args = p.parse_args()

    if not insight_db.is_ready:
        insight_db.initialize()
    if not insight_db.is_ready:
        print("InsightDB not configured (DATABASE_URL missing).")
        return 1

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=args.hours)).isoformat()
    rows = list(insight_db.container("analytics_events").query_items(
        query="SELECT * FROM c WHERE c.timestamp >= @cutoff ORDER BY c.timestamp",
        parameters=[{"name": "@cutoff", "value": cutoff}],
        enable_cross_partition_query=True,
    ))

    print(f"{len(rows)} event(s) in the last {args.hours}h")
    print(f"{'timestamp':<19}  {'duration':>11}  {'steps':>5}  cached  query")
    print("-" * 90)
    for r in rows:
        ts = (r.get("timestamp") or "")[:19]
        dur = r.get("duration_ms") or 0
        st = r.get("step_timings") or {}
        cached = "yes" if r.get("cached") else "no"
        q = (r.get("query_text") or "")[:40]
        print(f"{ts}  {dur:>9.1f}ms  {len(st):>5}  {cached:<6}  {q}")

    new_rows = sum(1 for r in rows if (r.get("duration_ms") or 0) > 0)
    print("-" * 90)
    print(f"with duration_ms > 0: {new_rows}/{len(rows)}  → these are post-restart rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
