# End-to-end implementation roadmap

## Delivery strategy

Build v2 in vertical slices behind server-side flags. Each promoted intent must work end to end—interpretation, resolution, tenancy, source route, computation, formatting, disclosure, UI, telemetry, tests, and rollback—before it is exposed to users.

Do not merge a half-deterministic path where the model still fills missing business logic. If a slice is incomplete, v1 remains active or the request is explicitly unsupported according to role and risk.

## Workstreams

Run these workstreams in parallel after ownership is assigned:

- **Data and ERP contract:** Phase 0 profiling, semantic views, sync version, assertions, post-sync hook.
- **Application core:** typed contracts, registry adapter/compiler, resolver, routing, execution, assembly.
- **Security/platform:** route authorization, DB roles, streaming, migrations, secrets, distributed jobs.
- **Incluziv APIs:** endpoint contracts, pagination, status/length mappings, rate limits, typed clients.
- **Frontend/UX:** interpretation, picker, disclosure, source/completeness, unsupported and fallback states.
- **Quality/operations:** fixtures, evaluation harness, CI, telemetry, dashboards, load and release gates.

One accountable owner should sign each acceptance gate. Product/data owners sign business definitions; engineering/security sign enforcement; QA signs evaluation evidence.

## Phase -1 — stabilize the foundation

Purpose: make v2 development reproducible and close security/reliability gaps that would invalidate production testing.

### Deliverables

- Select one frontend package manager, remove lockfile ambiguity through a reviewed change, and document exact setup commands.
- Pin/lock backend dependencies and add a reproducible local/test container.
- Add CI for backend tests, frontend typecheck/build/lint, migration validation, and secret scanning.
- Introduce reviewed database migrations; move future v2 DDL out of application startup.
- Authenticate and authorize all connection endpoints.
- Validate `workspace_id` and `connection_id` association on chat and scheduled execution.
- Replace arbitrary scope table/column parameters with server-side allowlists.
- Add a `RequestContext` shared by v1 wrappers and v2.
- Choose and implement the production streaming topology: preferably one authenticated streaming POST; otherwise a shared broker.
- Add distributed ownership/lease for scheduled prompts, or move scheduling to a single external scheduler.
- Add v2 feature flags and a kill switch, all defaulted off.
- Add correlation IDs and durable error logging; stop silently swallowing security/telemetry failures without a metric.

### Acceptance gate

- A user cannot list, test, delete, inspect, or use a connection outside an authorized workspace.
- Customer, manager, moderator, and admin authorization tests cover direct HTTP calls and crafted IDs.
- A chat request streams successfully under at least two backend instances without affinity.
- Existing v1 smoke tests pass with v2 disabled.
- CI produces one reproducible green baseline.

## Phase 0 — data contract and quality gates

Purpose: prove the source facts before encoding them.

### Deliverables

1. Capture the four-table schema, types, nullability, indexes, row counts, date ranges, and sample-safe profiling results.
2. Determine the full source/tenant/document key and whether `invoice_no` alone is unique.
3. Re-run post-dedup reconciliation using line taxes, with separate diagnostics for header-tax differences and GST-on-freight.
4. Analyze candidate natural keys, including legitimate identical lines. Do not create a unique index without an ERP-backed line identity.
5. Implement the duplicate alert as review-only and document false-positive handling.
6. Confirm:
   - `invoice.collection` authority;
   - `item_master.collection_name` meaning;
   - complete swatch rule;
   - stock status values and casing;
   - `piece_dispval` type, unit, null/negative/zero behavior;
   - territory meaning of `sales_person`;
   - absence/scope of returns and credit notes.
7. Define a monotonic `sync_version` and post-sync success contract.
8. Build an idempotent assertion job with an advisory lock, persisted run/result records, metrics, alerts, and a runbook.
9. Keep raw query output out of logs; retain counts, hashes, and safe examples.

### Stop conditions

- Material unexplained reconciliation residuals.
- Unknown document identity.
- Inability to distinguish a failed/partial sync from a successful one.
- Unresolved revenue or swatch definition.

### Acceptance gate

- Data owner signs the canonical definitions and source keys.
- Reconciliation result meets an agreed numeric threshold; “approximately zero” is replaced by an exact allowed count/value rule.
- All assertions are green for seven consecutive completed syncs.
- Alerts have an owner, severity, and response runbook.
- Phase 0 evidence is stored as versioned artifacts, not only terminal output.

## Phase 1 — semantic views and canonical registry boundary

Purpose: make grain and namespace mistakes structurally difficult.

### Deliverables

- Create validated line, header, sellable-stock, all-stock, and item-dimension views in a dedicated schema.
- Include real source/tenant keys and explicit data types.
- Grant the v2 runtime role access to approved views only.
- Define canonical metrics and dimensions through a `MetricRegistry` interface.
- Locate/import the existing insight registry or create a new versioned registry after team approval.
- Add registry release states: draft, validated, active, retired.
- Add a startup/publish validator against a cached schema snapshot.
- Add SQL-level metric fixtures that reconcile to signed control totals.
- Add a lint rule/test rejecting v2 recipes that reference raw tables or unqualified `collection`.

### Acceptance gate

- Canonical revenue, quantity, invoice count, courier, stock metres, pieces, and longest roll reconcile to control queries.
- Header inconsistencies are detected before the header view is relied on.
- Every initial recipe reads only approved semantic objects.
- Chat and any available insight-engine adapter resolve shared metric IDs to the same definition/version.
- Migration rollback has been rehearsed without removing base data.

## Phase 2 — resolver vertical slice

Purpose: remove runtime fuzzy SQL probing and make ambiguity visible.

### Deliverables

- Implement shared normalization with golden cases for punctuation, `&/and`, accents, whitespace, SKU separators, joined/split codes, numbers, units, and Hinglish stopwords.
- Create source-scoped entity, token, generation, and scoped alias storage.
- Build a post-sync staging generation and atomic activation job.
- Define stable entity IDs and picker-safe context for every entity type.
- Implement exact, prefix, and trigram retrieval plus token-intersection/ranking.
- Implement bounded IDF/scoring with deterministic tie-breakers.
- Implement intent type priors as versioned configuration.
- Implement fixed act/ask/decline outcomes.
- Add backend picker response and frontend picker interaction.
- Record picker choices as scoped evidence; add reviewed promotion flow.
- Log candidate sets, component scores, policy version, outcome, and chosen option.

### Required cases

- `acacia 50222` resolves to exactly the validated SKU.
- Bare `32373` evaluates both item ID and serial and asks when still close.
- `furnishing` does not silently choose among hundreds of customers.
- `floor and furnishing` produces a useful context-rich picker.
- `banglore` resolves/corrects according to calibrated fuzzy policy.
- “my/mera” for customer role bypasses lookup and cannot expose another customer.
- `60 m` is a quantity slot and never becomes resolver token `60`.

### Acceptance gate

- Zero `%LIKE%`/`ILIKE` entity probes on enabled deterministic intents.
- Resolver top-1/picker accuracy meets signed thresholds on labeled data.
- Every ambiguous decision is reproducible for the same resolver generation.
- Picker accessibility, mobile behavior, and role-safe context pass UX/security review.
- Previous resolver generation can be restored by pointer change.

## Phase 3 — classifier, recipes, query compiler, and tenancy

Purpose: establish the deterministic spine.

### Deliverables

- Implement the complete strict intent/slot schema and one repair retry.
- Implement code-owned defaults for current FY, top-N measure, `top_n`, and date boundaries.
- Implement registry recipes for an initial low-risk slice: sales summary, top-N, and stock summary.
- Compile queries with allowed identifiers and bound values.
- Add schema preflight at registry publication/startup, not on every healthy request unless schema version changes.
- Inject customer scope from `RequestContext`; use database permissions/RLS where feasible.
- Implement deterministic routing as recipe policy after resolution.
- Add explicit unsupported states for multi-customer outstanding and unsafe fallback.
- Log classifier version/output, defaults, resolution, recipe version, route, parameter types, and execution metadata.
- Add a shadow comparator that compares normalized v1/v2 results without showing v2.

### Acceptance gate

- Each recipe has contract, SQL integration, tenancy, default, malformed-input, and golden-answer tests.
- Adversarial prompts cannot remove or broaden customer scope.
- All values are bound parameters and all identifiers originate in registry allowlists.
- The interpretation shown to the user exactly matches executed parameters.
- Shadow comparisons meet agreed correctness and latency targets before canary.

## Phase 4 — answer assembly, formatting, state, and cache

Purpose: remove model arithmetic and make every answer self-describing.

### Deliverables

- Implement `Decimal`-based INR/full-value/crore/lakh formatting with finance-approved rounding.
- Implement typed aggregators; do not generically sum every numeric-looking field.
- Implement the pure roll-availability function.
- Create deterministic renderers for every enabled intent.
- Generate interpretation, scope, metric definition, period, freshness, exclusions, returns limitation, grouping limitations, and completeness disclosure in code.
- Create narration payload allowlists and numeric/date/percentage validation.
- Reject unsupported causal claims; fall back to deterministic rendering after two attempts.
- Persist structured `TurnRecord` state and implement follow-up binding/re-query rules.
- Replace v2 cache with `(recipe_version, canonical_params, scope, source_version)`.
- Disable cache for stock availability, outstanding, and order status initially.
- Add bounded retention, encryption/access rules, and deletion behavior for stored results.

### Acceptance gate

- Historical INR cases and corrected exact-value test fixtures pass.
- Roll cases for items 32373 and 53809 pass using frozen piece fixtures.
- Every displayed numeric token is payload-backed.
- Every quantitative answer has a visible, code-generated disclosure.
- Follow-ups cannot answer quantitative questions without stored results or a new read.
- Cache changes cannot cross source, registry, scope, period, or sync version.

## Phase 5 — live API routes

Purpose: safely support fresh stock, outstanding, and order status.

### External contract work

Obtain written answers from Incluziv for:

- cursor/`LAST_ID` request and response semantics;
- stable sort key and deduplication key;
- whether exactly 300 means capped;
- end-of-data indicator;
- rate limits and recommended concurrency;
- token lifetime/error contract;
- piece-length field/unit/precision;
- stock status field and whether non-sellable rows are included;
- API snapshot consistency across pages.

### Deliverables

- Typed clients for the three approved operations.
- Pooled transport, auth refresh, deadlines, bounded retries, rate handling, circuit breaker, and redacted logs.
- Pagination with page/row ceilings and explicit completeness.
- Code-computed balances/status counts/stock roll result.
- Live freshness labels and DB-fallback freshness downgrade.
- No multi-customer outstanding fan-out.
- API contract fixtures for normal, empty, malformed, duplicate, partial, timeout, capped, and changing-page responses.

### Acceptance gate

- One SKU routes to live API; aggregate stock routes to DB.
- One customer outstanding routes to live API; multiple customers get the parked response.
- No exactly-300/capped response is narrated as complete without proof.
- Stock yes/no is produced only by the domain function over verified sellable piece rows.
- API failure produces a truthful degraded/unsupported answer, never a fabricated total.

## Phase 6 — fallback, evaluation, and product completion

Purpose: support the long tail without reintroducing silent wrong answers.

### Deliverables

- Role/intent risk matrix for fallback:
  - customer financial/stock/outstanding: clarify or unsupported;
  - internal low-risk analytics: read-only fallback permitted;
  - cross-customer/customer-identifying fallback: privileged only and audited.
- AST validation, approved views, DB read-only role, statement timeout, row/byte limit, and confidence label.
- Fallback event store with user feedback and weekly frequency report.
- Headless 70-question + 12-contradiction evaluation runner.
- Frontend interpretation, picker, disclosure, freshness, completeness, low-confidence, correction, retry, and accessible error states.
- Admin dashboards for resolver quality, fallback frequency, validation rejection, route mix, source health, cost, and latency.
- Runbooks for data assertion failure, resolver rollback, API outage, registry rollback, stream failure, and tenant incident.

### Acceptance gate

- All 12 contradiction cases produce one correct answer across three runs on a frozen version.
- No category in the 70-question set regresses against the approved baseline.
- Unsupported questions are accurately labeled and useful to non-technical users.
- Fallback never bypasses tenancy or claims high confidence.
- Product, support, security, data, and operations sign the release checklist.

## Rollout sequence

1. **Development fixtures:** all v2 flags off outside local/test.
2. **Offline replay:** run the evaluation corpus and sanitized production logs; no user impact.
3. **DB-only shadow:** selected internal workspaces; no live API duplication.
4. **Internal canary:** deterministic sales summary/top-N/stock summary; v1 kill switch available.
5. **Customer canary:** a small allowlist, only intents meeting tenancy and UX gates.
6. **API canary:** one live operation at a time after contract approval.
7. **Intent-by-intent expansion:** promote based on evidence, not a single global launch.
8. **Default-on:** only after SLO, correctness, security, and support readiness hold for the agreed observation window.
9. **V1 retirement:** after fallback demand is low, rollback window closes, and stored sessions remain readable.

## Rollback model

- Flip affected intent/workspace to v1 or unsupported.
- Revert active registry/resolver generation pointers.
- Disable LLM narration while retaining deterministic rendering.
- Disable an unhealthy live API route and return last-sync data only when the recipe explicitly permits it.
- Preserve additive v2 tables for diagnosis; never drop or rewrite them during an incident.
- Record rollback reason and affected versions in the release log.

## Suggested first production slice

Start with **sales summary by period for one scoped customer** after Phase 0/1/security gates. It exercises scope, period defaults, canonical revenue, parameter binding, formatter, disclosure, state, cache versioning, and compatibility without depending on fuzzy item resolution or live API pagination.

Then add **top-N by collection/city**, **stock summary**, **single-SKU live stock**, **single-customer outstanding**, and **order status** in that order. Multi-customer outstanding stays parked.

## Definition of done for every intent

- Signed business definition and source/grain.
- Strict classifier and slot fixtures, including Hinglish/typos.
- Resolver behavior and picker UX where applicable.
- Deterministic route and cache policy.
- Bound query or typed API request.
- Tenancy and authorization tests.
- Complete/truncated/error behavior.
- Deterministic calculations and formatter tests.
- Code-generated interpretation/disclosure.
- Narration validation and template fallback.
- Structured follow-up state.
- Telemetry and alerting.
- Golden, integration, end-to-end, performance, and rollback evidence.
- Product/data/security/QA acceptance recorded.
