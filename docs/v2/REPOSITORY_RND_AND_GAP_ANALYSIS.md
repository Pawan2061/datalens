# Repository R&D and gap analysis

## Executive finding

The proposed deterministic direction is correct and directly addresses failures visible in the current implementation. The current repository is still a general-purpose ReAct analytics product: an LLM sees schema/profile text, decides between dynamic API tools and freehand SQL, executes raw SQL, and a second LLM synthesizes the answer. Several targeted mitigations exist, but the model still controls the SQL, route, entity choice, arithmetic selection, and final numeric claims.

The safest implementation is a strangler migration: keep v1 available, add a typed v2 application layer, and promote supported intents individually. A direct rewrite of `backend/app/agent/graph.py` would combine business migration, security changes, streaming changes, and UX changes in one high-risk release.

## Current request path

```text
React useChat
  -> EventSource GET /api/chat/stream/{session_id}
  -> POST /api/chat
  -> regex + LLM security checks, quota and role-derived scope
  -> graph.run_agent
  -> profile/schema prompt + dynamic API tools + execute_sql
  -> ReAct model selects route and creates SQL/tool parameters
  -> QueryRunner or HTTP API
  -> synthesis model creates narrative
  -> InsightResult over SSE
  -> client stores message history and later sends condensed prose back
```

Evidence:

- `backend/app/api/routes/chat.py` owns request validation and process-local SSE queues.
- `backend/app/agent/graph.py` builds the prompt, creates the ReAct agent, collects tool results, synthesizes, and caches the final answer.
- `backend/app/agent/tools/sql_executor.py` validates and executes model-provided SQL.
- `backend/app/agent/tools/api_tool_factory.py` exposes workspace-configured HTTP APIs as model-selectable tools.
- `frontend/src/hooks/useChat.ts` sends condensed prior prose as history.

## What can be reused

| Existing capability | Reuse decision | Required change |
|---|---|---|
| FastAPI authentication and roles | Reuse | Centralize authorization into a request context and apply it to chat, workspace, connection, API, and session access. |
| PostgreSQL application persistence | Reuse | Add real migrations, typed repositories, v2 turn state, registry metadata, audit events, feature flags, and alias scope. Do not continue adding production DDL only in a startup string. |
| SQLAlchemy async engines | Reuse | Add bound parameters, transaction-scoped read-only/timeout settings, approved-view allowlists, and correct truncation metadata. |
| Schema inspector/cache | Reuse behind an interface | Use it for trusted preflight validation. It must not be exposed as a freehand route and must understand views. |
| Dynamic Incluziv-compatible API adapter | Partially reuse | Add deterministic route ownership, typed endpoint contracts, pooled clients, pagination/cap semantics, status filtering, retries, and circuit breaking. |
| Server-derived customer scope | Reuse concept | Replace regex proof with construction-time enforcement and database defense-in-depth. |
| INR annotation code/tests | Reuse test evidence only | Move to a pure `Decimal` formatter with explicit rounding and separate currency/quantity types. |
| SSE event names and `InsightResult` | Reuse as compatibility envelope | Add optional interpretation, resolution, disclosure, source, confidence, and picker fields without breaking existing UI consumers. |
| Workspace/session persistence | Reuse for UI history | Add server-owned structured turn state; do not derive data referents from condensed assistant prose. |
| Existing API tool tests and load-test utility | Reuse and extend | Add deterministic-path contract, pagination, concurrency, isolation, stream, and correctness scenarios. |
| v1 freehand agent | Keep as controlled fallback | Initially internal-only, low-confidence, fully logged, parsed, scoped, read-only, and disabled for financially sensitive customer answers. |

## What is not present in this checkout

The source documents state that an insight-engine metric registry and its tables already exist. A search of tracked files across all local and `origin/*` refs found no metric registry, recipe registry, resolver, registry migrations, or evaluation harness. `backend/app/db/insight_db.py` contains application persistence tables, while `backend/app/schemas/insight.py` contains response and chart models; neither is a business metric registry.

Before implementation, the team must provide one of the following:

- the repository/branch/package and migrations containing the existing registry;
- access details for registry tables managed outside this repository; or
- approval to make this repository the source of truth for a new registry.

The adapter in the target architecture prevents this missing asset from blocking early data/view and contract work, but shared metrics cannot be declared production-ready until one authoritative registry is identified.

The named 70-question evaluation workbook and 12 contradiction cases are also absent. The two checked-in XLSX files are different datasets. They cannot substitute for the release corpus.

## Proposal-to-repository mapping

| Proposed component | Current repository state | Gap |
|---|---|---|
| Canonical line/header/stock views | No migrations or view definitions | Entirely new; production schema must be validated first. |
| Metric and recipe registry | Not visible in checkout | Asset/location decision required. |
| Strict intent classifier | Existing classifier is a security guardrail, not business intent classification | New schema, prompt, retries, fixtures, and telemetry required. |
| Entity resolver and aliases | No resolver tables or service | New source index, policy, UI picker, rebuild job, and audit trail required. |
| Deterministic API-vs-DB router | The ReAct model chooses tools | New code-owned routing table and typed API clients required. |
| Parameterized query builder | Current tool accepts a raw SQL string | New builder/executor contract required. |
| Code-generated disclosures | No structured disclosure model | Backend and frontend contract work required. |
| Numeric narration validator | Prompt rules only; no numeric-token validator | New validator and deterministic renderers required. |
| Structured follow-up state | Client sends truncated prose | New persistence model and server-side resolver required. |
| Sync-version cache | Question-normalized, process-local response cache | Replace for v2; disable for volatile intents. |
| Complete telemetry | Analytics stores cost, timings, row counts, and question | Add interpretation, candidates, decision, recipe/version, bound parameter hashes, source, truncation, validation, and outcome. |
| Headless evaluation gate | Not present | New fixture format, runner, baselines, and CI job required. |

## Existing behavior that already conflicts with the v2 rules

### Revenue definition

`backend/app/agent/prompts.py` currently instructs the model to calculate revenue from invoice header amount minus header GST totals and courier charges, deduplicated with `MAX`. The complete research explicitly rejects header tax totals and defines canonical revenue at line grain as `SUM(order_amt - COALESCE(discount_amt, 0))`.

This is not safe to repair only by editing the prompt. The v2 view and single metric definition must be created first, validated against production, then consumed by recipes.

### Route ownership

Dynamic API descriptions and SQL tools are handed to the ReAct agent. The model decides whether and how to call them. V2 requires `classify -> resolve -> route` with route selection in code after resolution.

### Roll availability

Current code computes numeric maxima for API results, but the final yes/no decision is still expressed as synthesis prompt instructions. There is no pure domain function returning `YES`, `NO_STOCK`, or `NO_SINGLE_PIECE`. The requested regression cases therefore are not structurally guaranteed.

### Arithmetic and formatting

Current code annotates large numbers before synthesis and has useful regression tests. It still:

- uses binary `float` for money;
- computes generic totals for every numeric column, including identifiers that happen to be numeric;
- allows the model to select which values to state;
- has no validator proving every narrated number came from the payload;
- does not generate a mandatory structured disclosure.

### Cache

The response cache normalizes natural-language text by stripping phrases and keys on connection, scope, mode, selected tables, and normalized question. It has no intent/parameters, registry version, or sync version. It also caches every non-empty result, including volatile API-backed answers. This directly conflicts with the proposed cache contract.

### Follow-ups

The client sends recent assistant titles/narratives back to the backend. The server has no persisted entity ID, selected candidate, recipe, parameters, or result reference for the turn. This explains why a quantitative follow-up can be answered from prose without a data read.

### Query execution

`QueryRunner.execute` receives one raw SQL string and calls `text(sql)` without a parameter map. `fetchmany(max_query_rows)` caps returned rows but does not communicate that another row exists, and a client-side `asyncio.wait_for` is not a complete database resource policy. V2 needs bound parameters, a server-side statement timeout, read-only transactions, `LIMIT N+1`/truncation semantics, and audited cancellation.

### Tenancy

There is a useful server-side scope derivation in the chat route and a regex backstop for raw `invoice`/`customer_master` SQL. It is insufficient for v2:

- the regex does not recognize proposed view names such as `v_invoice_line`;
- it checks text, not parsed query structure;
- it does not prove scope is applied inside every relevant branch/CTE;
- API scoping depends on parameter-name aliases in workspace configuration;
- the chat endpoint does not verify that the caller may use the submitted workspace and connection;
- connection CRUD/list/schema endpoints currently have no authentication dependency;
- `/api/scope/customers` interpolates client-supplied table and column identifiers into SQL.

These are release blockers, not deferred cleanup.

### Multi-instance streaming and scheduling

Chat POST state, ownership, and SSE queues are process-local dictionaries. The frontend opens an SSE GET and then posts the request. Cloud Run is configured for up to three backend instances, so the two requests can land on different instances and the stream can return `404 Session not found` or lose events.

The scheduled-prompt runner and prompt-cache warmer also start in every application instance. Without a distributed lease, scheduled work can run more than once and cache warming can multiply cost.

The v2 path should prefer one authenticated streaming POST request. If the two-request contract must remain, use a shared event broker and durable job state.

## Corrections and clarifications required in the source specification

These do not invalidate the proposal; they must be resolved before code becomes a source of truth.

1. **Reconciliation contradicts the tax rule.** Section 1.2 uses header tax totals, while §1.3 prohibits them. Reconciliation should use line taxes and separately report any freight/GST-on-freight residual. Header totals may be compared diagnostically, not treated as authoritative.
2. **Duplicate detector is heuristic.** `COUNT(*) / COUNT(DISTINCT line tuple)` does not prove that an entire line multiset was replayed, and it intentionally flags legitimate identical piece rows. It is an alert only. A reliable prevention key requires an ERP source-line ID, sync-run lineage, or an idempotency key from the sync team.
3. **Invoice identity may not be global.** `invoice_no` alone must be proven unique across company, tenant, branch, and financial year. Views and guards need the actual document key, not an assumed one.
4. **Two resolver schemas are proposed.** The technical spec has one `resolver_index`; the detailed resolver has `resolver_entity`, `resolver_token`, and `resolver_alias`. Adopt the latter, version it, and add source/workspace scope.
5. **Resolver scoring is not yet mathematically calibrated.** `1 / log(1 + token_df)` is greater than one at `df=1`, while policy thresholds assume bounded scores. Use a bounded IDF normalization and calibrate thresholds on labeled choices.
6. **Global alias learning is unsafe.** A single user's picker choice must not silently become the answer for every user. User/customer aliases remain scoped; workspace aliases require repeated evidence or review; global aliases are manual and audited.
7. **Intent contract does not cover the full catalogue.** The enum omits explicit trend/comparison and product-lookup intents, and the slots omit requested metres, grouping dimension, bucket, comparison period, warehouse, order/invoice reference, and detail mode.
8. **The formatter example contains an inconsistent expected value.** `1,219,489,509` rupees is `121.95 Cr`, not `1,219 Cr`. If the intended input was approximately `12,194,895,098`, record the exact value before pinning a test.
9. **Disclosure wording is ambiguous.** `order_amt - discount_amt` is after discount and excludes GST. The label should say `after line discount, excluding GST`, not `excl. discount`.
10. **Determinism acceptance needs a frozen source.** Three calls to a live API can legitimately change. Repeatability must compare calls against the same fixture/snapshot or assert routing/calculation invariants while allowing a newer freshness/version.
11. **Freehand fallback conflicts with hard-failure preference.** For customer-facing financial, outstanding, stock-availability, and cross-customer requests, unsupported should fail/clarify rather than execute freehand SQL. Initially allow fallback only for authorized internal users and low-risk read-only dimensions.
12. **“Hinglish costs nothing extra” is a hypothesis.** It still requires a labeled Hinglish evaluation set, typo cases, and monitoring by language.

## Production limitations to relay immediately

### Blocking

- Production data validations in Technical Specification Phase 0 have not been run from this repo.
- The authoritative metric registry named by the documents is unavailable in this checkout.
- The 70-question workbook and 12 contradiction transcripts are unavailable in this checkout.
- Incluziv cursor semantics, rate limits, completeness metadata, stock field mapping, and stock status filtering are unconfirmed.
- The daily outstanding table has not been located/profiled; multi-customer outstanding must remain unavailable.
- Workspace/connection authorization and multi-instance chat streaming need remediation before broader customer release.

### Material but non-blocking for early development

- There is no migrations framework or CI workflow.
- Backend dependency versions are partly ranged and there is no lock file.
- The frontend contains both npm and pnpm lockfiles; one package manager must be selected.
- The health endpoint reports application persistence readiness but not source DB, registry generation, sync freshness, or API health.
- Telemetry silently drops failures in several paths and has no retention/redaction policy.
- API clients are created per call rather than pooled.
- Current tests cover selected utilities but not the end-to-end business rules, authorization boundaries, or multi-instance transport.
- Runtime DDL privileges are asserted by research, but production runtime should be SELECT-only; migrations should use a separate deploy identity.

## Baseline verification performed

- Reviewed both DOCX documents in full.
- Inventoried all tracked files and searched all local/remotely tracked branch trees for registry/resolver/evaluation assets.
- Reviewed chat, graph, prompts, SQL execution/validation, API factory, persistence, scope, frontend session/history, deployment, and load-test paths.
- Counted 41 backend test functions at the audit baseline.
- Attempted backend and frontend verification without modifying dependencies:
  - backend: not runnable because the active Python environment lacks `pytest`;
  - frontend build: local dependencies/types are unavailable or stale, so the active compiler rejected current TypeScript options;
  - frontend lint: `eslint` is not installed in the active environment.

The implementation roadmap starts with a reproducible toolchain and clean baseline so v2 failures are not confused with environment drift.
