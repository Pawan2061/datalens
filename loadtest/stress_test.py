#!/usr/bin/env python3
"""
DataLens stress / load test.

Simulates many concurrent users hitting the API and reports latency
percentiles, throughput, and error rates so you can judge whether the
deployment handles a given level of concurrency.

SAFE BY DEFAULT
---------------
The default scenario ("read") only calls *read-only* GET endpoints
(/health, /api/auth/me, /api/workspaces, /api/connections, and per-workspace
GET sessions/canvas). It writes no data and triggers no LLM calls, so it is
safe to run against production.

The "chat" scenario drives the real LLM agent pipeline. It costs real money,
writes analytics rows, and will hit LLM-provider rate limits at high
concurrency. It is OFF unless you pass --scenario chat AND the explicit
--yes-this-costs-money flag.

USAGE
-----
  pip install httpx

  # 50-user read-only dry run against production (zero data impact):
  python stress_test.py \
      --url https://datalens.ainocular.com \
      --token "<paste a Bearer token from a logged-in browser session>" \
      --users 50 --duration 60

  # Pure infra ping, no auth needed:
  python stress_test.py --url https://datalens.ainocular.com \
      --scenario health --users 100 --duration 30

  # Ramp test: start at 50, step up to 1000 over the run:
  python stress_test.py --url https://datalens.ainocular.com --token "..." \
      --users 1000 --ramp 120 --duration 300

How to get a token: log in to the app in your browser, open DevTools →
Network, click any /api request, and copy the value after "Bearer " in the
Authorization request header. (Or DevTools → Application → Local Storage.)
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

try:
    import httpx
except ImportError:
    sys.exit("httpx is required:  pip install httpx")


# ── Result accounting ────────────────────────────────────────────────

@dataclass
class EndpointStats:
    latencies_ms: list[float] = field(default_factory=list)
    status_codes: Counter = field(default_factory=Counter)
    errors: Counter = field(default_factory=Counter)  # exception type -> count

    @property
    def count(self) -> int:
        return len(self.latencies_ms) + sum(self.errors.values())

    @property
    def ok(self) -> int:
        return sum(c for s, c in self.status_codes.items() if 200 <= s < 400)


class Metrics:
    def __init__(self) -> None:
        self.by_endpoint: dict[str, EndpointStats] = defaultdict(EndpointStats)
        self.start: float = 0.0
        self.end: float = 0.0

    def record(self, label: str, latency_ms: float | None, status: int | None,
               error: str | None) -> None:
        s = self.by_endpoint[label]
        if error is not None:
            s.errors[error] += 1
            return
        s.latencies_ms.append(latency_ms)  # type: ignore[arg-type]
        s.status_codes[status] += 1  # type: ignore[index]


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


# ── HTTP helpers ─────────────────────────────────────────────────────

async def timed_get(client: httpx.AsyncClient, metrics: Metrics, label: str,
                    path: str, **kwargs) -> httpx.Response | None:
    t0 = time.perf_counter()
    try:
        resp = await client.get(path, **kwargs)
        dt = (time.perf_counter() - t0) * 1000.0
        metrics.record(label, dt, resp.status_code, None)
        return resp
    except Exception as e:  # noqa: BLE001 - we want to bucket every failure
        metrics.record(label, None, None, type(e).__name__)
        return None


# ── Scenarios ────────────────────────────────────────────────────────
# A scenario is one "session" worth of work for a single virtual user.

async def scenario_health(client, metrics, headers, args, rng) -> None:
    await timed_get(client, metrics, "GET /health", "/health")


async def scenario_read(client, metrics, headers, args, rng) -> None:
    """A realistic read-only browsing session for one virtual user."""
    # 1. Auth check — every authenticated page load does this.
    await timed_get(client, metrics, "GET /api/auth/me", "/api/auth/me",
                    headers=headers)

    # 2. Load the workspace list (the home screen).
    resp = await timed_get(client, metrics, "GET /api/workspaces",
                           "/api/workspaces", headers=headers)
    await _think(rng, args)

    # 3. List connections (also loaded on the dashboard).
    await timed_get(client, metrics, "GET /api/connections",
                    "/api/connections", headers=headers)

    # 4. If we discovered any workspaces, "open" one: load its sessions
    #    and canvas, like a user clicking into a workspace.
    ws_ids: list[str] = []
    if resp is not None and resp.status_code == 200:
        try:
            data = resp.json()
            ws_ids = [w["id"] for w in data if isinstance(w, dict) and "id" in w]
        except Exception:  # noqa: BLE001
            ws_ids = []

    if ws_ids:
        wid = rng.choice(ws_ids)
        await _think(rng, args)
        await timed_get(client, metrics, "GET /api/workspaces/{id}/sessions",
                        f"/api/workspaces/{wid}/sessions", headers=headers)
        await timed_get(client, metrics, "GET /api/workspaces/{id}/canvas",
                        f"/api/workspaces/{wid}/canvas", headers=headers)


async def scenario_chat(client, metrics, headers, args, rng) -> None:
    """DANGER: drives the real LLM pipeline. Costs money. Off by default."""
    question = rng.choice([
        "What are the top 5 results by total?",
        "Show me the trend over the last 6 months.",
        "Give me a summary of the data.",
    ])
    payload = {
        "message": question,
        "workspace_id": args.workspace_id or "",
        "connection_id": args.connection_id or "",
        "analysis_mode": "auto",
    }
    t0 = time.perf_counter()
    try:
        resp = await client.post("/api/chat", json=payload, headers=headers)
        dt = (time.perf_counter() - t0) * 1000.0
        metrics.record("POST /api/chat", dt, resp.status_code, None)
        if resp.status_code != 200:
            return
        session_id = resp.json().get("session_id")
    except Exception as e:  # noqa: BLE001
        metrics.record("POST /api/chat", None, None, type(e).__name__)
        return

    if not session_id:
        return

    # Consume the SSE stream until it ends or times out.
    t0 = time.perf_counter()
    try:
        async with client.stream("GET", f"/api/chat/stream/{session_id}",
                                 headers=headers, timeout=args.chat_timeout) as r:
            async for _line in r.aiter_lines():
                pass
        dt = (time.perf_counter() - t0) * 1000.0
        metrics.record("SSE /api/chat/stream", dt, r.status_code, None)
    except Exception as e:  # noqa: BLE001
        metrics.record("SSE /api/chat/stream", None, None, type(e).__name__)


SCENARIOS = {
    "health": scenario_health,
    "read": scenario_read,
    "chat": scenario_chat,
}


async def _think(rng: random.Random, args) -> None:
    """Simulate human think-time between clicks."""
    if args.think_max > 0:
        await asyncio.sleep(rng.uniform(args.think_min, args.think_max))


# ── Virtual user loop ────────────────────────────────────────────────

async def virtual_user(uid: int, client, metrics, headers, args,
                        stop_at: float, started: list[int]) -> None:
    # Ramp: stagger user startup across the ramp window.
    if args.ramp > 0 and args.users > 1:
        delay = args.ramp * (uid / args.users)
        await asyncio.sleep(delay)
    started[0] += 1

    rng = random.Random(uid)
    scenario = SCENARIOS[args.scenario]
    while time.perf_counter() < stop_at:
        await scenario(client, metrics, headers, args, rng)
        await _think(rng, args)


async def progress_reporter(metrics: Metrics, stop_at: float,
                            started: list[int], total_users: int) -> None:
    while time.perf_counter() < stop_at:
        await asyncio.sleep(5)
        total = sum(s.count for s in metrics.by_endpoint.values())
        errs = sum(sum(s.errors.values()) for s in metrics.by_endpoint.values())
        bad = sum(c for s in metrics.by_endpoint.values()
                  for code, c in s.status_codes.items() if code >= 400)
        elapsed = time.perf_counter() - metrics.start
        rps = total / elapsed if elapsed > 0 else 0
        print(f"  [{elapsed:5.0f}s] users={started[0]}/{total_users} "
              f"requests={total} rps={rps:6.1f} "
              f"errors={errs} http4xx/5xx={bad}", flush=True)


# ── Reporting ────────────────────────────────────────────────────────

def print_report(metrics: Metrics, args) -> None:
    wall = metrics.end - metrics.start
    total = sum(s.count for s in metrics.by_endpoint.values())
    total_ok = sum(s.ok for s in metrics.by_endpoint.values())
    total_err = sum(sum(s.errors.values()) for s in metrics.by_endpoint.values())

    print("\n" + "=" * 78)
    print(f"  DataLens stress test report")
    print("=" * 78)
    print(f"  target          : {args.url}")
    print(f"  scenario        : {args.scenario}")
    print(f"  virtual users   : {args.users}  (ramp {args.ramp}s)")
    print(f"  wall time       : {wall:.1f}s")
    print(f"  total requests  : {total}")
    print(f"  overall RPS     : {total / wall if wall else 0:.1f}")
    print(f"  success (2xx/3xx): {total_ok}  "
          f"({100 * total_ok / total if total else 0:.1f}%)")
    print(f"  transport errors: {total_err}")
    print("-" * 78)
    header = (f"  {'endpoint':<34}{'n':>6}{'ok%':>6}"
              f"{'p50':>8}{'p90':>8}{'p99':>8}{'max':>8}")
    print(header + "   (ms)")
    print("-" * 78)
    for label in sorted(metrics.by_endpoint):
        s = metrics.by_endpoint[label]
        lat = s.latencies_ms
        n = s.count
        okp = 100 * s.ok / n if n else 0
        print(f"  {label:<34}{n:>6}{okp:>6.0f}"
              f"{_pct(lat, 50):>8.0f}{_pct(lat, 90):>8.0f}"
              f"{_pct(lat, 99):>8.0f}{(max(lat) if lat else 0):>8.0f}")

    # Status code + error breakdown (only if anything interesting happened).
    codes: Counter = Counter()
    errs: Counter = Counter()
    for s in metrics.by_endpoint.values():
        codes.update(s.status_codes)
        errs.update(s.errors)
    if any(c >= 400 for c in codes) or errs:
        print("-" * 78)
        print("  non-2xx status codes & transport errors:")
        for code, c in sorted(codes.items()):
            if code >= 400:
                print(f"    HTTP {code}: {c}")
        for name, c in errs.most_common():
            print(f"    {name} (transport): {c}")
    print("=" * 78)

    # A blunt verdict.
    err_rate = (total_err + sum(c for code, c in codes.items() if code >= 500)) \
        / total if total else 1
    p99_overall = _pct([x for s in metrics.by_endpoint.values()
                        for x in s.latencies_ms], 99)
    print("\n  VERDICT:")
    if err_rate > 0.01:
        print(f"  ⚠️  error rate {100 * err_rate:.1f}% — the deployment is "
              f"struggling at {args.users} concurrent users.")
    elif p99_overall > 3000:
        print(f"  ⚠️  errors low but p99 latency is {p99_overall:.0f}ms — "
              f"slow under this load; investigate before going higher.")
    else:
        print(f"  ✅  healthy at {args.users} users: error rate "
              f"{100 * err_rate:.2f}%, p99 {p99_overall:.0f}ms. "
              f"Try a higher --users to find the ceiling.")
    print()


# ── Main ─────────────────────────────────────────────────────────────

async def run(args) -> None:
    headers = {}
    if args.token:
        headers["Authorization"] = f"Bearer {args.token}"

    if args.scenario != "health" and not args.token:
        sys.exit("This scenario needs auth. Pass --token <Bearer token>.")

    metrics = Metrics()
    limits = httpx.Limits(max_connections=args.users + 10,
                          max_keepalive_connections=args.users + 10)
    timeout = httpx.Timeout(args.timeout, connect=10.0)

    print(f"Starting: {args.users} users, scenario='{args.scenario}', "
          f"target={args.url}, duration={args.duration}s, ramp={args.ramp}s")
    if args.scenario == "chat":
        print("⚠️  CHAT scenario active — this is making REAL LLM calls and "
              "costing money.")

    async with httpx.AsyncClient(base_url=args.url, limits=limits,
                                 timeout=timeout,
                                 follow_redirects=True) as client:
        metrics.start = time.perf_counter()
        stop_at = metrics.start + args.duration + args.ramp
        started = [0]
        tasks = [
            asyncio.create_task(
                virtual_user(i, client, metrics, headers, args, stop_at, started))
            for i in range(args.users)
        ]
        reporter = asyncio.create_task(
            progress_reporter(metrics, stop_at, started, args.users))
        await asyncio.gather(*tasks, return_exceptions=True)
        reporter.cancel()
        metrics.end = time.perf_counter()

    print_report(metrics, args)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="DataLens stress / load test")
    p.add_argument("--url", required=True,
                   help="Base URL, e.g. https://datalens.ainocular.com")
    p.add_argument("--token", default=None,
                   help="Bearer token for authenticated scenarios")
    p.add_argument("--scenario", choices=list(SCENARIOS), default="read",
                   help="read (safe, default) | health (no auth) | chat (COSTS MONEY)")
    p.add_argument("--users", type=int, default=50,
                   help="Number of concurrent virtual users (default 50)")
    p.add_argument("--duration", type=float, default=60,
                   help="Seconds to sustain load after ramp (default 60)")
    p.add_argument("--ramp", type=float, default=0,
                   help="Seconds to stagger user startup over (default 0)")
    p.add_argument("--think-min", type=float, default=0.5,
                   help="Min think-time between actions, seconds")
    p.add_argument("--think-max", type=float, default=2.0,
                   help="Max think-time between actions, seconds (0 = no delay)")
    p.add_argument("--timeout", type=float, default=30.0,
                   help="Per-request timeout, seconds")
    p.add_argument("--chat-timeout", type=float, default=120.0,
                   help="SSE stream timeout for chat scenario, seconds")
    p.add_argument("--workspace-id", default=None,
                   help="Workspace id for the chat scenario")
    p.add_argument("--connection-id", default=None,
                   help="Connection id for the chat scenario")
    p.add_argument("--yes-this-costs-money", action="store_true",
                   help="Required confirmation to run the chat scenario")
    args = p.parse_args()

    if args.scenario == "chat" and not args.yes_this_costs_money:
        sys.exit("Refusing to run the 'chat' scenario without "
                 "--yes-this-costs-money (it makes real, billable LLM calls).")
    return args


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("\nInterrupted.")
