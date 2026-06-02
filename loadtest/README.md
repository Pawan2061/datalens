# DataLens load / stress test

`stress_test.py` simulates many concurrent users and reports latency
percentiles, throughput, and error rates.

## Setup

```bash
pip install httpx
cd loadtest
```

## Get a token (for authenticated scenarios)

1. Log in to https://datalens.ainocular.com in your browser.
2. Open DevTools → **Network** tab.
3. Click any `/api/...` request, look at **Request Headers**.
4. Copy the value after `Bearer ` in the `Authorization` header.

(Token is a 72-hour JWT, so it stays valid for the test.)

## Scenarios

| Scenario | What it hits | Data impact | Cost |
|----------|--------------|-------------|------|
| `read` (default) | `GET /api/auth/me`, `/api/workspaces`, `/api/connections`, per-workspace sessions/canvas | **None** (read-only) | $0 |
| `health` | `GET /health` only (no auth) | None | $0 |
| `chat` | `POST /api/chat` + SSE stream → full LLM pipeline | Writes analytics rows | **Real LLM $$$** |

## The 50-user dry run you asked for (zero data impact)

```bash
python stress_test.py \
  --url https://datalens.ainocular.com \
  --token "PASTE_YOUR_BEARER_TOKEN" \
  --users 50 \
  --duration 60
```

This runs 50 virtual users for 60 seconds, each looping a realistic
read-only browsing session (auth check → load workspaces → load connections →
open a workspace) with human-like think-time pauses between clicks. Nothing
is written, no LLM is called.

## Finding the ceiling (still safe — read-only)

Step up `--users` and add a ramp so you don't slam every user on at once:

```bash
# 200 users
python stress_test.py --url https://datalens.ainocular.com --token "..." \
  --users 200 --ramp 30 --duration 120

# 1000 users, ramped in over 2 min
python stress_test.py --url https://datalens.ainocular.com --token "..." \
  --users 1000 --ramp 120 --duration 300

# 5000 users (peak target)
python stress_test.py --url https://datalens.ainocular.com --token "..." \
  --users 5000 --ramp 300 --duration 300
```

Watch the VERDICT line and the per-endpoint p99 / error columns. When error
rate climbs above ~1% or p99 spikes, you've found the current ceiling.

## Reading the report

- **ok%** — share of 2xx/3xx responses per endpoint. Drops here = overload.
- **p50 / p90 / p99 (ms)** — latency. p99 is what your slowest users feel.
- **HTTP 429** — quota/rate-limit kicking in. **HTTP 5xx** — server failing.
- **transport errors** (ConnectTimeout, ReadTimeout, etc.) — the server
  stopped accepting/answering connections; the hard ceiling.

## Notes / caveats

- Run this from a machine with good bandwidth. At thousands of users the
  bottleneck can become *your* laptop's CPU/network, not the server — if so,
  run it from a cloud VM in the same region, or split across machines.
- Cloud Run autoscales on concurrent requests; the first burst after idle
  hits cold starts, so expect a higher p99 in the first few seconds of a run.
- `GET /api/workspaces` for a regular user does `SELECT *` over all workspaces
  and filters in Python — keep an eye on its p99 specifically as you scale.
- This is **single-region, single-token** load. To also exercise per-user
  quota and DB partitioning realistically, run with several different tokens
  (one per role) in parallel terminals.
