"""Read-only verification of cost_usd against the live Postgres store.

Recomputes what every ``usage_logs`` row's ``cost_usd`` *should* have been,
given the cache-token breakdown stored alongside it, and dumps the raw tables
plus a per-row / per-day / per-user diff to an Excel workbook.

Usage::

    DATABASE_URL=postgresql://user:pwd@host/db?sslmode=require \
        python -m scripts.verify_costs
    python -m scripts.verify_costs -o ./cost_audit.xlsx

The script is **read-only** — no UPDATE/INSERT/DELETE statements are issued.
Each fetch runs inside a transaction with ``SET LOCAL
default_transaction_read_only = on`` so the read-only flag cannot leak through
PgBouncer to the next session sharing the pooled connection.

Why two cost columns?
    * ``cost_usd_buggy_recalc`` — what the production formula would compute
      today (it bills cache tokens twice because LangChain's ``input_tokens``
      is fresh + cache_read + cache_creation, not fresh-only).
    * ``cost_usd_corrected`` — what the formula computes after subtracting
      the cache portion from input first, AND with Sonnet 4.6 / Opus 4.7
      added to the pricing table (today they fall through to the $1/$5
      fallback and are understated).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import psycopg
import psycopg.rows


# ── Corrected pricing table (per 1M tokens) ───────────────────────────
# Source: https://platform.claude.com/docs/en/about-claude/pricing.
# Order matters: longer / more specific keys first.
# Note vs. earlier iterations of this script: Haiku 4.5 is $1/$5 (not the
# Haiku 3.5 $0.8/$4) and Opus 4.7/4.6/4.5 are $5/$25 (not the older $15/$75).
_PRICING: list[tuple[str, dict[str, float]]] = [
    ("claude-sonnet-4-6", {"input": 3.0, "output": 15.0}),
    ("claude-sonnet-4-5", {"input": 3.0, "output": 15.0}),
    ("claude-sonnet-4-20250514", {"input": 3.0, "output": 15.0}),
    ("claude-sonnet-4", {"input": 3.0, "output": 15.0}),
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
]
_FALLBACK_PRICING = {"input": 1.0, "output": 5.0}  # matches production fallback


def _resolve_pricing(model_name: str) -> tuple[dict[str, float], bool]:
    """Return (pricing, matched). matched=False means we hit the $1/$5 fallback."""
    m = (model_name or "").lower()
    for key, p in _PRICING:
        if key in m:
            return p, True
    return _FALLBACK_PRICING, False


def _buggy_cost(row: dict) -> float:
    """Reproduce production ``_estimate_cost`` exactly, including its bugs.

    Bug 1 (cache double-count): ``input_tokens`` is treated as fresh, but
    LangChain's ``usage_metadata.input_tokens`` already includes cache reads
    and cache writes, so the cache portion gets billed twice.

    Bug 2 (pricing table gaps): Sonnet 4.6 / Opus 4.7 fall to the $1/$5
    fallback because their ids don't substring-match anything in the
    production dict.
    """
    prod_pricing = {
        "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
        "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
        "claude-haiku-4-5": {"input": 0.8, "output": 4.0},
        "claude-opus-4-0": {"input": 15.0, "output": 75.0},
        "gpt-4o": {"input": 2.5, "output": 10.0},
        "gpt-4.1-mini": {"input": 0.4, "output": 1.6},
        "gemini-2.0-flash": {"input": 0.0, "output": 0.0},
        "gemini-2.5-flash": {"input": 0.0, "output": 0.0},
        "gemini": {"input": 0.0, "output": 0.0},
    }
    m = (row.get("model_name") or "").lower()
    pricing = next((p for k, p in prod_pricing.items() if k in m), {"input": 1.0, "output": 5.0})

    inp = int(row.get("input_tokens") or 0)
    out = int(row.get("output_tokens") or 0)
    cr = int(row.get("cache_read_tokens") or 0)
    cw = int(row.get("cache_creation_tokens") or 0)

    return round(
        (inp * pricing["input"] / 1_000_000)
        + (out * pricing["output"] / 1_000_000)
        + (cw * pricing["input"] * 1.25 / 1_000_000)
        + (cr * pricing["input"] * 0.10 / 1_000_000),
        6,
    )


def _correct_cost(row: dict, est_cw: int = 0) -> tuple[float, bool]:
    """Compute what the cost should have been: fresh-only input + correct pricing.

    ``est_cw`` lets the caller substitute an *estimated* cache_creation count
    when the stored value is 0 due to the langchain-anthropic 1.4 capture bug.
    Pass 0 (default) to compute the strict floor straight from stored columns.
    """
    pricing, matched = _resolve_pricing(row.get("model_name") or "")

    inp = int(row.get("input_tokens") or 0)
    out = int(row.get("output_tokens") or 0)
    cr = int(row.get("cache_read_tokens") or 0)
    cw_stored = int(row.get("cache_creation_tokens") or 0)
    cw = cw_stored or est_cw
    fresh = max(inp - cr - cw, 0)

    cost = round(
        (fresh * pricing["input"] / 1_000_000)
        + (out * pricing["output"] / 1_000_000)
        + (cw * pricing["input"] * 1.25 / 1_000_000)
        + (cr * pricing["input"] * 0.10 / 1_000_000),
        6,
    )
    return cost, matched


def _estimate_cache_creation(usage_logs: pd.DataFrame) -> pd.Series:
    """Heuristic estimate of the cache_creation tokens that langchain dropped.

    For each Anthropic row with stored ``cache_creation_tokens == 0``, the
    estimate is:

      * 0 if ``cache_read_tokens > 0`` (some other request — likely the warmer
        or an earlier user request — already paid the write cost; no write
        attributable to this row)
      * 0 if ``input_tokens`` is below the per-model median read size (prompt
        was too small to have triggered caching)
      * otherwise, the per-model median ``cache_read_tokens`` (from rows that
        did read the cache) — this is the typical static-prefix size that
        would have been written when the cache went cold

    This is an *upper bound* on user-attributable writes; if a warmer is
    running it absorbs most cold-start writes, so true user writes will be
    lower. It is only used to bracket the cost impact in the audit, not
    written back to the DB.
    """
    if usage_logs.empty:
        return pd.Series([], dtype=int)

    is_anth = usage_logs["model_name"].astype(str).str.lower().str.contains("claude", na=False)
    # Per-model median prefix size from rows that actually hit the cache.
    hits = usage_logs[is_anth & (usage_logs["cache_read_tokens"].astype(int) > 0)]
    if hits.empty:
        return pd.Series([0] * len(usage_logs), index=usage_logs.index, dtype=int)
    medians = (
        hits.groupby("model_name")["cache_read_tokens"]
        .median()
        .astype(int)
        .to_dict()
    )

    est = []
    for _, row in usage_logs.iterrows():
        if not is_anth.loc[row.name]:
            est.append(0); continue
        if int(row.get("cache_creation_tokens") or 0) > 0:
            est.append(0); continue  # already captured, don't double-count
        if int(row.get("cache_read_tokens") or 0) > 0:
            est.append(0); continue  # someone else paid for the write
        med = int(medians.get(row.get("model_name"), 0) or 0)
        inp = int(row.get("input_tokens") or 0)
        est.append(med if (med > 0 and inp >= med) else 0)
    return pd.Series(est, index=usage_logs.index, dtype=int)


def _to_psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _safe_host(url: str) -> str:
    try:
        p = urlparse(_to_psycopg_url(url))
        return f"{p.hostname}:{p.port or 5432}{p.path}"
    except Exception:
        return "<unparseable>"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-o", "--output", default="", help="Output xlsx path (default: ./cost_audit_<TS>.xlsx)")
    p.add_argument("--limit", type=int, default=0, help="Cap rows per table (0 = no cap)")
    args = p.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("ERROR: DATABASE_URL not set. Export it before running.", file=sys.stderr)
        return 2

    print(f"Connecting to {_safe_host(db_url)} (read-only)...")
    conn_str = _to_psycopg_url(db_url)

    with psycopg.connect(conn_str) as conn:
        def _ro_fetch(table: str) -> pd.DataFrame:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("SET LOCAL default_transaction_read_only = on")
                with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    cur.execute(f"SELECT * FROM {table}")
                    rows = cur.fetchall()
                return pd.DataFrame(rows)

        usage_logs = _ro_fetch("usage_logs")
        users = _ro_fetch("users")
        analytics_events = _ro_fetch("analytics_events")

    if args.limit > 0:
        usage_logs = usage_logs.head(args.limit)
        analytics_events = analytics_events.head(args.limit)

    print(f"  usage_logs:        {len(usage_logs):>6} rows")
    print(f"  users:             {len(users):>6} rows")
    print(f"  analytics_events:  {len(analytics_events):>6} rows")

    # ── Per-row recompute on usage_logs ──────────────────────────────
    recompute = usage_logs.copy()
    if recompute.empty:
        print("usage_logs is empty — nothing to recompute.")
        for col in ("cost_usd_buggy_recalc", "cost_usd_corrected", "pricing_matched",
                    "cost_delta_db_minus_corrected", "cost_delta_db_minus_buggyrecalc"):
            recompute[col] = []
    else:
        recompute["cost_usd_buggy_recalc"] = recompute.apply(lambda r: _buggy_cost(r.to_dict()), axis=1)
        # Floor scenario: stored cache_creation only (treats missing writes as 0).
        floor = recompute.apply(lambda r: _correct_cost(r.to_dict()), axis=1)
        recompute["cost_usd_corrected"] = [c for c, _ in floor]
        recompute["pricing_matched"] = [m for _, m in floor]
        # Estimate scenario: fill in the writes langchain dropped.
        recompute["estimated_cache_creation_tokens"] = _estimate_cache_creation(recompute)
        est = recompute.apply(
            lambda r: _correct_cost(r.to_dict(), int(r["estimated_cache_creation_tokens"]))[0],
            axis=1,
        )
        recompute["cost_usd_corrected_estimated"] = est
        recompute["cost_delta_db_minus_corrected"] = (
            recompute["cost_usd"].astype(float) - recompute["cost_usd_corrected"]
        ).round(6)
        recompute["cost_delta_db_minus_buggyrecalc"] = (
            recompute["cost_usd"].astype(float) - recompute["cost_usd_buggy_recalc"]
        ).round(6)

    # ── Aggregates ──────────────────────────────────────────────────
    if not recompute.empty:
        daily = recompute.copy()
        daily["day"] = daily["timestamp"].astype(str).str[:10]
        per_day = daily.groupby("day", as_index=False).agg(
            rows=("id", "count"),
            stored_total=("cost_usd", "sum"),
            corrected_total=("cost_usd_corrected", "sum"),
        )
        per_day["overstatement"] = (per_day["stored_total"] - per_day["corrected_total"]).round(4)
        per_day["pct_overstated"] = (
            100.0 * per_day["overstatement"] / per_day["stored_total"].replace(0, pd.NA)
        ).round(2)
        per_day = per_day.sort_values("day", ascending=False, ignore_index=True)

        per_user = recompute.groupby("user_id", as_index=False).agg(
            rows=("id", "count"),
            stored_total=("cost_usd", "sum"),
            corrected_total=("cost_usd_corrected", "sum"),
        )
        per_user["overstatement"] = (per_user["stored_total"] - per_user["corrected_total"]).round(4)
        per_user["pct_overstated"] = (
            100.0 * per_user["overstatement"] / per_user["stored_total"].replace(0, pd.NA)
        ).round(2)
        per_user = per_user.sort_values("overstatement", ascending=False, ignore_index=True)

        unmatched = recompute[~recompute["pricing_matched"]][[
            "id", "user_id", "model_name", "input_tokens", "output_tokens",
            "cache_read_tokens", "cache_creation_tokens", "cost_usd", "cost_usd_corrected",
        ]].sort_values("cost_usd", ascending=False).reset_index(drop=True)
    else:
        per_day = pd.DataFrame(columns=["day", "rows", "stored_total", "corrected_total", "overstatement", "pct_overstated"])
        per_user = pd.DataFrame(columns=["user_id", "rows", "stored_total", "corrected_total", "overstatement", "pct_overstated"])
        unmatched = pd.DataFrame()

    # ── Corrected views (drop-in for the fix) ───────────────────────
    if not recompute.empty:
        usage_logs_corrected = usage_logs.copy()
        usage_logs_corrected["cost_usd"] = recompute["cost_usd_corrected"].values

        if not users.empty and "id" in users.columns:
            agg = recompute.copy()
            ts = agg["timestamp"].astype(str)
            today_str = datetime.utcnow().strftime("%Y-%m-%d")
            month_str = datetime.utcnow().strftime("%Y-%m")
            agg["_is_today"] = ts.str[:10] == today_str
            agg["_is_month"] = ts.str[:7] == month_str
            per_user_costs = agg.groupby("user_id").agg(
                total_cost_usd_corrected=("cost_usd_corrected", "sum"),
                month_cost_usd_corrected=(
                    "cost_usd_corrected",
                    lambda s: s[agg.loc[s.index, "_is_month"]].sum(),
                ),
                today_cost_usd_corrected=(
                    "cost_usd_corrected",
                    lambda s: s[agg.loc[s.index, "_is_today"]].sum(),
                ),
            ).reset_index().rename(columns={"user_id": "id"})

            users_corrected = users.merge(per_user_costs, on="id", how="left")
            for col, src in [
                ("today_cost_usd", "today_cost_usd_corrected"),
                ("month_cost_usd", "month_cost_usd_corrected"),
                ("total_cost_usd", "total_cost_usd_corrected"),
            ]:
                if col in users_corrected.columns and src in users_corrected.columns:
                    users_corrected[col] = users_corrected[src].fillna(
                        users_corrected[col]
                    ).round(6)
            users_corrected = users_corrected.drop(
                columns=[c for c in [
                    "total_cost_usd_corrected", "month_cost_usd_corrected", "today_cost_usd_corrected",
                ] if c in users_corrected.columns],
                errors="ignore",
            )
        else:
            users_corrected = users.copy()
    else:
        usage_logs_corrected = usage_logs.copy()
        users_corrected = users.copy()

    # ── Net totals (the bottom-line view) ────────────────────────────
    net_rows: list[dict] = []
    if not recompute.empty:
        stored_total = float(recompute["cost_usd"].astype(float).sum())
        corrected_total = float(recompute["cost_usd_corrected"].sum())
        overstatement = stored_total - corrected_total
        pct = (100.0 * overstatement / stored_total) if stored_total else 0.0
        net_rows.append({
            "scope": "ALL ROWS",
            "rows": int(len(recompute)),
            "input_tokens_total": int(recompute["input_tokens"].astype(int).sum()),
            "output_tokens_total": int(recompute["output_tokens"].astype(int).sum()),
            "cache_read_total": int(recompute["cache_read_tokens"].astype(int).sum()),
            "cache_creation_total": int(recompute["cache_creation_tokens"].astype(int).sum()),
            "total_tokens": int(recompute["total_tokens"].astype(int).sum()),
            "stored_cost_usd": round(stored_total, 4),
            "corrected_cost_usd": round(corrected_total, 4),
            "overstatement_usd": round(overstatement, 4),
            "pct_overstated": round(pct, 2),
        })
        for uid, sub in recompute.groupby("user_id"):
            stored_u = float(sub["cost_usd"].astype(float).sum())
            corrected_u = float(sub["cost_usd_corrected"].sum())
            over_u = stored_u - corrected_u
            pct_u = (100.0 * over_u / stored_u) if stored_u else 0.0
            net_rows.append({
                "scope": f"user_id={uid}",
                "rows": int(len(sub)),
                "input_tokens_total": int(sub["input_tokens"].astype(int).sum()),
                "output_tokens_total": int(sub["output_tokens"].astype(int).sum()),
                "cache_read_total": int(sub["cache_read_tokens"].astype(int).sum()),
                "cache_creation_total": int(sub["cache_creation_tokens"].astype(int).sum()),
                "total_tokens": int(sub["total_tokens"].astype(int).sum()),
                "stored_cost_usd": round(stored_u, 4),
                "corrected_cost_usd": round(corrected_u, 4),
                "overstatement_usd": round(over_u, 4),
                "pct_overstated": round(pct_u, 2),
            })
        net_rows[1:] = sorted(net_rows[1:], key=lambda r: r["overstatement_usd"], reverse=True)
    net_totals = pd.DataFrame(net_rows)

    # ── Write workbook ───────────────────────────────────────────────
    if args.output:
        out = Path(args.output).expanduser().resolve()
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(f"cost_audit_{stamp}.xlsx").resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(out, engine="openpyxl") as w:
        if not net_totals.empty:
            net_totals.to_excel(w, sheet_name="Net Totals", index=False)
        if not per_day.empty:
            per_day.to_excel(w, sheet_name="Per Day", index=False)
        if not per_user.empty:
            per_user.to_excel(w, sheet_name="Per User", index=False)
        recompute.to_excel(w, sheet_name="Cost Recompute", index=False)
        if not unmatched.empty:
            unmatched.to_excel(w, sheet_name="Pricing Fallback Rows", index=False)
        usage_logs_corrected.to_excel(w, sheet_name="usage_logs (corrected)", index=False)
        users_corrected.to_excel(w, sheet_name="users (corrected)", index=False)
        usage_logs.to_excel(w, sheet_name="usage_logs (raw)", index=False)
        users.to_excel(w, sheet_name="users (raw)", index=False)
        analytics_events.to_excel(w, sheet_name="analytics_events (raw)", index=False)

    # ── Slim, single-sheet drop-in for diffing against Neon studio ───
    if not usage_logs_corrected.empty:
        slim_cols = [
            "id", "user_id", "questions",
            "input_tokens", "fresh_input_tokens",
            "output_tokens", "total_tokens",
            "cache_read_tokens", "cache_creation_tokens",
            "estimated_cache_creation_tokens",
            "cost_usd",
            "cost_usd_corrected_estimated",
            "cost_per_1k_total_tokens",
            "model_name", "timestamp",
        ]
        slim = usage_logs_corrected.copy()
        slim["fresh_input_tokens"] = (
            slim["input_tokens"].astype(int)
            - slim["cache_read_tokens"].astype(int)
            - slim["cache_creation_tokens"].astype(int)
        ).clip(lower=0)
        slim["cost_per_1k_total_tokens"] = (
            slim["cost_usd"].astype(float)
            / slim["total_tokens"].astype(float).replace(0, pd.NA)
            * 1000
        ).round(6)
        slim["cost_usd_old"] = usage_logs["cost_usd"].astype(float).values
        # Carry the estimate columns through from `recompute` (aligned by id).
        for col in ("estimated_cache_creation_tokens", "cost_usd_corrected_estimated"):
            if col in recompute.columns:
                slim[col] = recompute.set_index("id").reindex(slim["id"])[col].values
        slim = slim[[c for c in slim_cols if c in slim.columns] + ["cost_usd_old"]]
        slim = slim.sort_values("timestamp", ascending=True, ignore_index=True)
        slim_out = out.parent / out.name.replace("cost_audit_", "usage_logs_corrected_")
        with pd.ExcelWriter(slim_out, engine="openpyxl") as w:
            slim.to_excel(w, sheet_name="usage_logs (corrected)", index=False)
        print(f"Wrote corrected table → {slim_out}")

    # ── Console summary ──────────────────────────────────────────────
    if not recompute.empty:
        stored_total = float(recompute["cost_usd"].astype(float).sum())
        correct_total = float(recompute["cost_usd_corrected"].sum())
        overstatement = stored_total - correct_total
        pct = (100.0 * overstatement / stored_total) if stored_total else 0.0
        est_total = float(recompute.get("cost_usd_corrected_estimated", pd.Series(dtype=float)).sum())
        est_writes = int(recompute.get("estimated_cache_creation_tokens", pd.Series(dtype=int)).sum())
        print()
        print("──────── Cost audit summary ────────")
        print(f"  Rows:                          {len(recompute):,}")
        print(f"  Stored total:                  ${stored_total:.4f}")
        print(f"  Corrected total (writes=0):    ${correct_total:.4f}")
        print(f"  Corrected total (est. writes): ${est_total:.4f}  (+{est_writes:,} est. write tokens)")
        print(f"  Overstatement (vs floor):      ${overstatement:.4f}  ({pct:.1f}%)")
        if not unmatched.empty:
            unmatched_models = sorted(unmatched["model_name"].unique().tolist())
            print(f"  Pricing-fallback:              {len(unmatched)} row(s) — models: {unmatched_models}")
    print(f"\nWrote workbook → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
