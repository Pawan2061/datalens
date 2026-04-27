"""Export per-query step timings from ``analytics_events`` to an Excel file.

Usage (run from the ``backend/`` directory so the ``app`` package resolves):

    python -m scripts.export_timings                              # last 30 days, all workspaces
    python -m scripts.export_timings --days 7                     # last 7 days
    python -m scripts.export_timings --workspace ws-12345         # filter by workspace
    python -m scripts.export_timings --output ./timings.xlsx      # custom output path

All durations are exported in **seconds** (2 decimals). The workbook has:

* ``Queries`` — one row per query with the standard fields, ``duration_s``,
  one ``step_<name>_s`` column per recorded step, and a derived ``other_s``
  (total minus the sum of recorded steps) so you can spot uninstrumented
  latency.
* ``Step Summary`` — calls, avg / p50 / p95 / max / total seconds per step,
  sorted by average so the slowest phase floats to the top.

The script is read-only — it does not mutate any data.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Make the ``app`` package importable when this script is run as
# ``python scripts/export_timings.py`` from the backend directory.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.db.insight_db import insight_db  # noqa: E402

# ── Standard columns we always export, in this order ──────────────────
_BASE_COLUMNS = [
    "id",
    "timestamp",
    "user_email",
    "workspace_id",
    "connection_id",
    "analysis_mode",
    "model_name",
    "query_text",
    "cached",
    "duration_s",
    "sub_query_count",
    "total_rows",
    "tokens_used",
    "cost_usd",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--days", type=int, default=30, help="Look-back window in days (default: 30)")
    p.add_argument(
        "--hours", type=float, default=0.0,
        help="Look-back window in hours. Overrides --days when > 0 (e.g. --hours 1).",
    )
    p.add_argument("--workspace", default="", help="Filter by workspace_id")
    p.add_argument("--user-email", default="", help="Filter by user email")
    p.add_argument(
        "--output", "-o",
        default="",
        help="Output xlsx path (default: ./query_timings_<YYYYMMDD_HHMMSS>.xlsx)",
    )
    p.add_argument(
        "--limit", type=int, default=0,
        help="Max rows to export (0 = no limit)",
    )
    p.add_argument(
        "--exclude-cached", action="store_true",
        help="Drop in-app ResponseCache hits (default: include them — they have a meaningful cache_lookup timing and tiny duration).",
    )
    p.add_argument(
        "--include-empty", action="store_true",
        help="Include rows with no step_timings (legacy events from before this feature was deployed). Off by default so you only see rows with the breakdown.",
    )
    return p.parse_args()


def _fetch_events(
    days: int,
    hours: float,
    workspace: str,
    user_email: str,
    limit: int,
    exclude_cached: bool,
    include_empty: bool,
) -> list[dict]:
    """Pull analytics events from the configured store (Cosmos-style API)."""
    # The FastAPI app runs ``initialize`` on startup; standalone scripts must
    # do the same before the connection pool exists.
    if not insight_db.is_ready:
        insight_db.initialize()
    if not insight_db.is_ready:
        raise RuntimeError(
            "Persistence is not configured — set DATABASE_URL (or the equivalent "
            "Cosmos credentials) in your environment before running this script."
        )

    if hours > 0:
        window = timedelta(hours=hours)
    else:
        window = timedelta(days=max(days, 1))
    cutoff = (datetime.now(timezone.utc) - window).isoformat()

    where = ["c.timestamp >= @cutoff", "c.event_type = @evt"]
    params: list[dict] = [
        {"name": "@cutoff", "value": cutoff},
        {"name": "@evt", "value": "query"},
    ]
    if workspace:
        where.append("c.workspace_id = @wid")
        params.append({"name": "@wid", "value": workspace})
    if user_email:
        where.append("c.user_email = @uemail")
        params.append({"name": "@uemail", "value": user_email})

    query = (
        "SELECT * FROM c WHERE "
        + " AND ".join(where)
        + " ORDER BY c.timestamp DESC"
    )

    container = insight_db.container("analytics_events")
    items = list(container.query_items(
        query=query,
        parameters=params,
        enable_cross_partition_query=True,
    ))
    if exclude_cached:
        # Done in Python so it works whether the backing store is Postgres
        # or Cosmos and whether the row pre-dates the ``cached`` column.
        items = [it for it in items if not it.get("cached")]
    if not include_empty:
        # Keep only rows recorded after the timing feature shipped — i.e.
        # rows that actually carry a per-step breakdown.
        items = [it for it in items if _normalize_step_timings(it.get("step_timings"))]
    if limit > 0:
        items = items[:limit]
    return items


def _normalize_step_timings(raw) -> dict[str, float]:
    """Return a {step_name: ms} dict, parsing JSON strings if needed.

    Values stay in ms (raw form on disk) — conversion to seconds happens at
    the dataframe-build layer so the filter logic isn't affected.
    """
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        try:
            out[str(k)] = round(float(v), 2)
        except (TypeError, ValueError):
            continue
    return out


def _ms_to_s(ms: float | None) -> float | str:
    """Convert ms → seconds (2 decimals); blank string for None."""
    if ms is None:
        return ""
    return round(ms / 1000.0, 2)


def _build_query_dataframe(events: list[dict]) -> tuple[pd.DataFrame, list[str]]:
    """Flatten step_timings into ``step_<name>_ms`` columns.

    Returns the dataframe and the ordered list of step names encountered, so
    the caller can build the per-step summary sheet.
    """
    # First pass: collect all step names in stable insertion order.
    step_names: list[str] = []
    seen: set[str] = set()
    for e in events:
        for name in _normalize_step_timings(e.get("step_timings")):
            if name not in seen:
                seen.add(name)
                step_names.append(name)

    rows: list[dict] = []
    for e in events:
        timings = _normalize_step_timings(e.get("step_timings"))
        row: dict[str, object] = {col: e.get(col, "") for col in _BASE_COLUMNS if col != "duration_s"}
        # Total duration: stored as ms, exported as seconds.
        try:
            total_ms = float(e.get("duration_ms") or 0)
        except (TypeError, ValueError):
            total_ms = 0.0
        row["duration_s"] = _ms_to_s(total_ms) if total_ms else 0
        # Per-step columns (seconds).
        recorded_total = 0.0
        for name in step_names:
            v = timings.get(name)
            row[f"step_{name}_s"] = _ms_to_s(v)
            if v is not None:
                recorded_total += v
        # Latency we couldn't attribute to any named step (network, FastAPI,
        # guardrails not yet instrumented, etc.). Negative values are clamped
        # to 0 — they only happen when timer overlap rounds the sum above the
        # wall-clock total by a few ms.
        row["other_s"] = (
            _ms_to_s(max(total_ms - recorded_total, 0.0))
            if total_ms else ""
        )
        rows.append(row)

    columns = (
        _BASE_COLUMNS
        + [f"step_{n}_s" for n in step_names]
        + ["other_s"]
    )
    return pd.DataFrame(rows, columns=columns), step_names


def _build_summary_dataframe(events: list[dict], step_names: list[str]) -> pd.DataFrame:
    """Aggregate per-step latency: avg / p50 / p95 / max / count, in seconds."""
    rows: list[dict] = []
    for name in step_names:
        values: list[float] = []
        for e in events:
            v = _normalize_step_timings(e.get("step_timings")).get(name)
            if v is not None and v > 0:
                values.append(v)
        if not values:
            continue
        s = pd.Series(values) / 1000.0  # ms → seconds
        rows.append({
            "step": name,
            "calls": len(values),
            "avg_s": round(s.mean(), 2),
            "p50_s": round(s.median(), 2),
            "p95_s": round(s.quantile(0.95), 2),
            "max_s": round(s.max(), 2),
            "total_s": round(s.sum(), 2),
        })
    df = pd.DataFrame(
        rows,
        columns=["step", "calls", "avg_s", "p50_s", "p95_s", "max_s", "total_s"],
    )
    if not df.empty:
        df = df.sort_values("avg_s", ascending=False, ignore_index=True)
    return df


def _resolve_output_path(arg: str) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(f"query_timings_{stamp}.xlsx").resolve()


def main() -> int:
    args = _parse_args()
    window_label = f"{args.hours}h" if args.hours > 0 else f"{args.days}d"
    notes: list[str] = []
    if args.exclude_cached:
        notes.append("excluding cached")
    if not args.include_empty:
        notes.append("only rows with step timings")
    note_str = f" ({', '.join(notes)})" if notes else ""
    print(f"Fetching analytics events (last {window_label}){note_str}...")
    events = _fetch_events(
        args.days, args.hours, args.workspace, args.user_email, args.limit,
        exclude_cached=args.exclude_cached,
        include_empty=args.include_empty,
    )
    print(f"  → {len(events)} event(s) fetched")

    if not events:
        print("Nothing to export. Try a wider --days window or remove filters.")
        return 0

    queries_df, step_names = _build_query_dataframe(events)
    summary_df = _build_summary_dataframe(events, step_names)

    output = _resolve_output_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        queries_df.to_excel(writer, sheet_name="Queries", index=False)
        summary_df.to_excel(writer, sheet_name="Step Summary", index=False)

    print(f"Wrote {len(queries_df)} rows × {len(queries_df.columns)} cols to {output}")
    if not summary_df.empty:
        print("Top 3 slowest steps (by avg):")
        for _, r in summary_df.head(3).iterrows():
            print(f"  - {r['step']}: avg {r['avg_s']}s, p95 {r['p95_s']}s ({r['calls']} calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
