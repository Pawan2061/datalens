# Test, audit, and production-readiness plan

## Quality model

V2 correctness is a data contract, not an LLM impression. Every release produces evidence at five levels:

1. source-data assertions;
2. pure domain and contract tests;
3. database/API integration tests;
4. end-to-end question evaluation;
5. canary production telemetry and rollback rehearsal.

No single aggregate “accuracy” percentage is sufficient. Report pass rates by intent, language, role, source, ambiguity class, and defect category, with sample counts.

## Baseline gaps

At the repository audit baseline:

- 41 backend test functions exist, concentrated around API-tool transport/auth, caches/cost, INR annotations, email, and quota;
- no resolver, registry, semantic-view, classifier-contract, narration-validator, structured-state, or v2 routing tests exist;
- no route-level authorization tests cover connection management;
- no frontend unit/E2E test runner is configured;
- no CI workflow or migration test is checked in;
- the named 70-question workbook and 12 contradiction cases are missing;
- the available environment was not dependency-complete, so existing suites could not be established as green.

The first test task is to create a reproducible baseline, not to weaken or skip checks.

## Required fixture sets

### Data fixtures

- Single-line and multi-line invoices.
- Legitimately identical piece lines and intentionally replayed line multisets.
- Consistent and inconsistent header attributes.
- Null/incorrect header taxes with valid line taxes.
- Discounts: null, zero, line-varying, and boundary decimals.
- Intrastate/interstate tax patterns and freight/GST-on-freight residuals.
- Swatch and non-swatch lines.
- Returns/credit-note absence and, if later added, representative records.
- Active, quarantine, in-transit, null-status, zero-length, negative-length, and duplicate stock pieces.
- Duplicate invoice numbers across any discovered company/branch/FY boundary.

### Resolver fixtures

- All source-document examples: ACACIA 50222, 32373, furnishing, floor and furnishing, banglore, Anubhai Amarshi.
- Same label across types.
- Same numeric token as item ID and serial.
- Serial duplicates across collections.
- Punctuation, `&/and`, accents, whitespace, hyphens, slashes, joined/split codes.
- Typos at multiple edit distances.
- Stopwords, units, and quantities that must not become entity tokens.
- Dormant versus active namesake.
- No-match and more-than-eight candidates.
- Alias scope and attempted alias poisoning.

### API fixtures

- Empty, one-row, under-cap, exactly-cap, over-cap/paginated, and page-ceiling responses.
- Repeated rows across pages and unstable page ordering.
- Missing cursor/end marker.
- Token expiry, HTTP 429/5xx, timeout, malformed JSON, schema drift, and partial payload.
- String/decimal/null numeric fields.
- Piece length and status mappings.
- Quarantine/in-transit rows mixed with active rows.
- Outstanding balance versus invoice amount columns.

### Conversation fixtures

- The 70 source questions verbatim, with language and defect tags.
- The 12 contradiction transcripts with turn boundaries.
- Follow-ups using “it/that/iska/usi ka/same item”.
- Role changes and scope changes between sessions.
- Multi-part questions and unsupported questions.
- Prompt injection and requests for another customer's data.
- Non-technical user correction, picker cancel, back, retry, and stale-session flows.

## Test layers

### Pure unit tests

Run without a database or network:

- normalization/tokenization;
- fiscal period parsing and half-open ranges;
- classifier schema validation and defaults;
- resolver score components and deterministic ordering;
- act/ask/decline policy boundaries;
- route policy matrix;
- metric/recipe validation;
- `Decimal` INR, lakh, crore, quantity, percentage, and negative/null formatting;
- stock roll state machine;
- disclosure assembly;
- numeric/date token allowlisting and causal-claim rejection;
- cache canonicalization and version keys;
- structured follow-up referent selection;
- role/intent fallback matrix.

Use property-based tests for formatter round trips, range boundaries, normalization idempotence, cache canonicalization, and tenant-filter invariants.

### Database contract tests

Run against the supported PostgreSQL major version in an ephemeral container:

- migrations up/down or forward/rollback strategy;
- exact view columns and forbidden column absence;
- line/header grain and control totals;
- swatch and sellable-stock filters;
- canonical metric queries;
- parameter binding and injection strings;
- view-only runtime permissions;
- RLS/security behavior if enabled;
- resolver generation build, atomic activation, advisory lock, and rollback;
- index use with `EXPLAIN (ANALYZE, BUFFERS)` on representative scale;
- schema drift/fingerprint behavior;
- server-side timeout and read-only transaction enforcement;
- result truncation detected using `N+1`.

Production data checks should output counts and hashes, not customer details, into CI artifacts.

### API contract tests

Use a local stub server and recorded, sanitized schemas. Verify request parameters, authentication refresh, pagination, completeness, filtering, deduplication, retry budget, circuit breaker, and redaction. Never make real Incluziv calls in normal CI.

Run a separate approved staging contract test against Incluziv before API promotion.

### Service integration tests

Call the v2 application service with a fake classifier and real resolver/registry/test DB:

- every route-table branch;
- classification repair then failure;
- picker/resume with an authenticated turn token;
- customer self-scope and internal named-customer scope;
- unsupported multi-customer outstanding;
- API downgrade to last sync;
- no-data versus source-error distinction;
- session re-query and stored-result paths;
- registry/resolver/sync version propagation;
- narration rejection and deterministic fallback.

### HTTP and frontend E2E tests

Use Playwright or equivalent for:

- login and workspace authorization;
- a full deterministic response stream;
- interpretation and disclosure visibility;
- picker selection with keyboard/mobile viewport;
- stale picker and changed resolver generation;
- stream reconnect/cancel/retry;
- fallback/unsupported/completeness badges;
- persisted history across reload;
- export containing the same scoped data and disclosure;
- customer attempts to manipulate scope, workspace, connection, and entity choice.

### Evaluation harness

Represent each case as versioned data, not spreadsheet-only logic:

```yaml
id: top_collections_nagpur_last_fy
question: give me top 10 collections sold in nagpur for last financial year
role: internal
as_of: 2026-09-01
expected:
  intent: top_n
  route: db
  metric: net_sales_ex_gst
  group_by: collection
  period: [2025-04-01, 2026-04-01]
  resolution:
    entity_type: city
    canonical_label: NAGPUR
  result_fixture: nagpur_fy_2025_26
tags: [hinglish_or_english, top_n_default, period, city]
```

Separate scoring:

- classifier exact/acceptable match;
- entity top-1, top-k, correct picker, and false-auto-act rate;
- route correctness;
- recipe/parameter correctness;
- numeric result equality/tolerance;
- required disclosure fields;
- narration unsupported-number rate;
- end-to-end answer correctness;
- repeated-run determinism on a frozen source.

False auto-selection is more severe than asking an extra clarification and must have a stricter threshold.

## Security audit matrix

Before any customer canary, test:

- unauthenticated access to every `/api` route;
- horizontal workspace, connection, session, stream, canvas, export, and API-tool access;
- vertical role escalation;
- crafted `customer_scope`, `customer_scope_field`, source ID, recipe, entity ID, and picker option;
- SQL injection through entity text, period, dimension, sort, `top_n`, table/column identifiers, aliases, and fallback;
- scope enforcement in CTEs, joins, unions, nested queries, views, and API requests;
- indirect prompt injection in database/API content;
- SSRF including DNS resolution, redirects, IPv6, link-local/metadata addresses, and non-HTTP schemes;
- secret/token/PII leakage in prompts, logs, errors, SSE URLs, telemetry, and exports;
- alias poisoning and cross-workspace leakage;
- stale or replayed picker/stream tokens;
- retention/deletion and least-privilege DB roles.

Run a cross-tenant differential test: create two customers with distinctive canary records, execute the same adversarial suite for each, and fail on any marker from the other tenant.

## Data-quality audit

Each successful nightly run records:

- sync version and upstream run identifier;
- source max timestamps and row-count deltas;
- schema fingerprint;
- duplicate alert count and reviewed disposition;
- invoice header consistency violations;
- line-tax reconciliation distribution and residual buckets;
- null/invalid metric inputs;
- collection namespace overlap;
- status distribution and unknown values;
- resolver entity/token counts by type and change percentage;
- build duration and active generation.

Use severity levels:

- **Block serving new version:** missing/partial sync, schema incompatibility, unresolved metric columns, resolver build failure.
- **Disable affected metric/intent:** material reconciliation issue, new stock status, missing API field.
- **Alert/review:** duplicate heuristic candidates, unusual but bounded distribution shifts.

Never auto-delete source records from an assertion.

## Performance and scale tests

Initial targets must be ratified against infrastructure cost and current baselines. Suggested starting SLOs:

| Operation | Initial target |
|---|---|
| Resolver exact/prefix P95 | <= 100 ms |
| Resolver fuzzy/picker P95 | <= 250 ms |
| Registry compile/cache hit P95 | <= 25 ms |
| DB deterministic request excluding narration P95 | <= 2 s |
| End-to-end DB intent P95 | <= 6 s |
| End-to-end live API intent P95 | <= 10 s, subject to Incluziv SLO |
| Availability | >= 99.9% monthly for deterministic DB intents |
| Server error rate | < 1% at agreed peak concurrency |

Test with realistic distributions, not only health/read endpoints:

- exact, ambiguous, and fuzzy resolver traffic;
- hot/cold registry and schema caches;
- one-customer and aggregate DB recipes;
- streamed responses and client cancellations;
- upstream API latency/failure injection;
- multiple backend instances;
- sync/resolver build concurrent with reads;
- scheduled prompts concurrent with chat;
- cache stampede and connection-pool exhaustion;
- large but permitted result sets and exports.

Track CPU, memory, DB pool wait, SQL duration, rows scanned, API concurrency, LLM tokens, event-stream duration, and per-stage queueing.

## Telemetry contract

One structured turn event should include:

- request/session/turn IDs and pseudonymous user/tenant/workspace IDs;
- role and enforced scope type;
- question hash plus encrypted/redacted text according to retention policy;
- classifier model/schema/version, output, retries, and latency;
- resolver generation, tokens, candidates/scores, decision, and user choice;
- metric, recipe, registry version, typed parameters, route, and source version;
- SQL template ID and hash, never secrets; bound-value logging must be redacted;
- DB/API status, page count, completeness, rows, bytes, and stage timings;
- cache policy/key version/hit;
- assembly and narration-validator outcomes;
- fallback/unsupported/degraded flags;
- final response hash and user feedback.

Dashboards/alerts:

- correctness proxy: picker override rate, validator rejection, repeat mismatch;
- fallback/unsupported frequency by normalized intent cluster;
- data freshness/assertion health;
- API cap/rate/error/circuit state;
- tenant-scope blocks;
- P50/P95/P99 latency by stage and intent;
- error and no-data rates;
- cache hit/staleness prevention;
- cost per successful answer.

Telemetry failure must emit a metric. Whether it blocks the user should follow a documented availability/privacy policy; silently ignoring every failure is not auditable.

## Release evidence checklist

For every canary expansion, attach:

- code revision and migration versions;
- active registry, resolver, classifier, template, and sync versions;
- data-quality run links;
- unit/integration/E2E/evaluation reports;
- security test report;
- performance result and capacity assumptions;
- v1/v2 shadow diff summary with adjudicated mismatches;
- known limitations and user-facing wording;
- dashboards and alert owners;
- rollout cohort and observation window;
- tested rollback command/flag and owner;
- product, data, engineering, QA, security, and operations sign-offs as applicable.

## Production acceptance

V2 is production-ready for an intent only when:

- numbers match signed fixtures/control queries;
- frozen-source repeated runs are identical;
- live-source answers preserve calculation invariants and honest freshness/completeness;
- zero unauthorized cross-customer results occur;
- all numeric narration is payload-backed;
- mandatory disclosure is present;
- ambiguous entities never silently resolve outside policy;
- no capped page is called a total;
- SLOs hold through the canary window;
- rollback has been rehearsed;
- support has a runbook and can explain limitations to non-technical users.
