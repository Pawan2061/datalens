# Target architecture

## Design goal

DataLens v2 is a deterministic business-query application embedded in the existing analytics product. The model interprets language and optionally narrates a locked answer payload. Code owns identity, scope, source, query shape, computation, formatting, freshness, and fallback policy.

```text
authenticated request
  -> authorize workspace + connection
  -> build immutable RequestContext
  -> classify into a typed TurnIntent
  -> resolve entity slots from a versioned index
  -> apply deterministic act/ask/decline policy
  -> select recipe and source in code
  -> build bound query or typed API request
  -> execute under tenant and resource policy
  -> assemble typed metrics + disclosure
  -> render deterministic answer or validate LLM narration
  -> persist structured TurnRecord + audit event
  -> stream backward-compatible response events
```

## Migration boundary

Create a new package rather than expanding the existing monolithic graph:

```text
backend/app/datalens_v2/
  contracts.py              # Pydantic request/result contracts and enums
  context.py                # authenticated RequestContext
  service.py                # application orchestration only
  feature_flags.py          # off/shadow/canary/on and intent allowlist
  classification/
    normalizer.py
    classifier.py
    prompts.py
  resolution/
    models.py
    normalizer.py
    repository.py
    scoring.py
    policy.py
    service.py
  registry/
    models.py
    repository.py
    validator.py
    compiler.py
  routing/
    policy.py
  execution/
    db_executor.py
    api_client.py
    tenancy.py
  domain/
    fiscal_periods.py
    money.py
    stock.py
    disclosures.py
  narration/
    payload.py
    validator.py
    templates.py
  state/
    repository.py
    followups.py
  telemetry/
    events.py
    repository.py
```

The existing `run_agent` remains v1. A thin chat facade selects v1 or v2 by server-side feature flag. V2 emits the current SSE event names and `InsightResult` fields where possible, adding only optional metadata. This keeps current clients working while the frontend adds richer v2 components.

## Runtime contracts

Use strict Pydantic models and enums. No untyped dictionary should cross a component boundary in the deterministic path.

### Request context

`RequestContext` is created once from authenticated server data:

- `request_id`, `session_id`, `turn_id`;
- `user_id`, role, organization/tenant, workspace, connection/source;
- immutable `customer_code` for customer role;
- permissions/capabilities;
- locale and timezone;
- active registry version, resolver generation, and sync version.

Client input cannot supply or override these security fields.

### Intent

The classifier returns a strict schema, for example:

- intent: sales summary, top-N, stock availability, stock summary, outstanding, order status, invoice detail, product lookup, purchases, trend, comparison, courier cost, follow-up, or other;
- entity slots containing only entity text and an optional type hint;
- metric and group-by dimension;
- fiscal/month/date-range period;
- `top_n`;
- requested roll length in metres;
- bucket/comparison period;
- order/invoice reference;
- detail/list mode;
- language.

Validation rules reject unknown enums, extra fields, invalid dates, `top_n` outside a configured range, negative lengths, and impossible slot combinations. One schema repair retry is permitted. Failure becomes an explicit unsupported/fallback decision, not a partially parsed request.

Dates are converted immediately to half-open boundaries in the business timezone. For example, FY 2025-26 is `[2025-04-01, 2026-04-01)`. SQL never compares display labels such as `2025-26`.

### Resolution outcome

The resolver returns one of:

- `Resolved` with typed canonical IDs and labels;
- `NeedsChoice` with 2–8 safe display options;
- `NeedsSpecificity` with top suggestions and a total candidate count;
- `NotFound` with nearest safe matches;
- `SessionScoped`, when “my/mera” maps to the authenticated customer;
- `NotApplicable`, when an intent has no entity slot.

The application service cannot route or execute until resolution is terminal.

### Recipe and result

A recipe is declarative metadata referencing one canonical metric definition. It contains:

- supported intent and required/optional slots;
- source view or typed API operation;
- permitted dimensions and filters;
- default metric/period and disclosure text;
- route condition based on resolved entity type/cardinality;
- maximum result size and allowed roles;
- deterministic renderer ID;
- cache policy.

`MetricResult` carries typed rows, aggregates, row count, completeness/truncation, source version, and exact raw values. `AnswerPayload` adds formatted values, interpretation, disclosure, and the complete allowlist of numeric tokens the narrator may use.

## Data placement

### Analytics/source database

Create a dedicated managed schema, for example `datalens_semantic`, using a deployment identity:

- `v_invoice_line`;
- `v_invoice_header`;
- `v_stock_sellable` and `v_stock_all`;
- an approved item dimension exposing `collection_name` only as `item_category`;
- resolver entities/tokens and a generation marker;
- data-quality run and assertion result tables if operations want source-local evidence.

The runtime application identity receives `SELECT` only on approved views and resolver objects. Revoke direct base-table access from that identity after shadow validation. If the existing generic connection must retain broader access for v1, use a separate v2 connection/role.

Views must include the true tenant/company/document key. Do not publish the sample DDL until Phase 0 confirms columns, nullability, types, invoice identity, swatch rule, and exact status values.

### Application PostgreSQL

Store control-plane and conversational state here:

- registry versions/definitions or a pointer to the externally supplied registry;
- intent-to-recipe mappings;
- feature flags and canary assignments;
- resolver aliases with source/workspace/user scope;
- structured session turns and bounded result references;
- fallback events and user feedback;
- detailed turn telemetry;
- active sync version and source health if not source-local.

Use Alembic or an equivalent reviewed migration tool. Stop treating application startup as the primary migration mechanism.

## Canonical semantic layer

### Revenue

Use one definition everywhere:

```text
net_sales_ex_gst = SUM(order_amt - COALESCE(discount_amt, 0))
```

Final business label, subject to Phase 0 validation:

```text
Net sales before GST, after line discount, gross of returns
```

Do not call this net of returns because returns/credit notes are absent. Do not use header tax totals. If `order_amt` is already discount-adjusted in the ERP contract, change the definition once in the canonical metric and update reconciliation evidence before release.

### Grain

- Line metrics use only the line view.
- Invoice counts, courier/freight, credit terms, and document totals use only the header view.
- Stock availability uses sellable piece rows.
- Invalid invoices that violate header consistency are surfaced in data-quality results; the view must not hide conflicts with an arbitrary `MAX` without a green assertion.

Enforce view use both in the registry validator and with database permissions.

## Resolver design

Adopt the refined entity/postings structure, scoped by source:

```text
resolver_generation(source_id, generation_id, built_at, sync_version, status)
resolver_entity(source_id, generation_id, entity_type, entity_id,
                canonical_label, context, activity_weight)
resolver_token(source_id, generation_id, token, entity_type, entity_id,
               field, field_weight, token_df)
resolver_alias(source_id, scope_type, scope_id, input_norm,
               entity_type, entity_id, status, evidence_count,
               created_by, reviewed_by, last_used_at)
```

Important properties:

- A single shared normalizer implementation is used during build and lookup.
- An item receives postings from item ID, serial, collection, design, quality, shade, and supported joined-code variants.
- Query quantities, units, stopwords, and Hinglish particles do not enter the entity slot.
- Exact, prefix, and trigram matches are deterministic and separately measured.
- Multi-token matching ranks the maximum matched-token tier, then applies bounded match quality, IDF, field, type, and activity factors.
- Scores and tie-breakers are stable, with a final lexical ID tie-break so ordering never depends on query-plan order.
- Thresholds are configuration tied to a resolver version and released only after evaluation.
- Customer picker choices are user/customer-scoped. Workspace promotion requires review or sufficient repeated evidence. Global aliases are manual.
- Picker context contains only role-safe attributes. Customer users never receive other customers as options.

Rebuild into a new generation, validate counts and probes, then atomically switch an active-generation pointer. Keep the prior generation for immediate rollback. Use an advisory lock so two schedulers cannot publish concurrently.

## Registry and query compilation

Introduce a `MetricRegistry` interface first. It allows the missing external registry to be connected without coupling v2 to a guessed schema.

Recommended layers:

1. canonical metric definition: expression, grain, units, default filters, disclosure;
2. dimension definition: qualified view column, entity type, role policy;
3. recipe: intent, source, required slots, allowed dimensions, renderer, cache;
4. published registry release: immutable version and validation report.

Prefer structured recipes compiled with SQLAlchemy Core or a small internal query AST. If reviewed SQL templates are retained, only identifiers selected from allowlists may be composed; values are always bound parameters. Never interpolate user or resolver text.

Registry publish validation must reject:

- raw base tables;
- unqualified or unknown columns;
- a metric used at the wrong grain;
- ambiguous `collection` references;
- missing customer scope capability on tenanted recipes;
- volatile recipes with caching enabled;
- route rules not covered by tests;
- unsupported dimensions/filters;
- SQL with DDL/DML, multiple statements, or unsafe functions.

## Tenancy and authorization

Defense in depth:

1. authenticate every route;
2. authorize workspace membership and connection ownership/association;
3. derive customer code and role from the user record;
4. pass immutable scope through `RequestContext`;
5. compile the customer predicate into every tenanted query and API request;
6. use a restricted DB role and, where feasible, PostgreSQL RLS/security-barrier views;
7. validate final result scope before assembly;
8. log scope without exposing it to model-controlled parameters.

Stock/catalogue reads are permitted only through an explicit non-tenanted allowlist. “The query did not touch a customer table” is not sufficient proof by itself.

For fallback SQL, use an AST parser, approved views, one statement, bound values where possible, and fail closed if scope cannot be proven. Regex remains only a supplementary signal.

## Deterministic routing

Routing is a pure function of published recipe metadata plus resolved entities:

| Intent/outcome | Route | Cache |
|---|---|---|
| One exact SKU stock check | Live stock API | Off |
| Collection/warehouse/design stock aggregate | Sellable-stock DB view | Off initially |
| One-customer outstanding | Live outstanding API | Off |
| Multi-customer outstanding | Unsupported/parked | Off |
| Order status | Live order API | Off |
| Sales, top-N, trends, courier, purchase history | Semantic DB views | Sync-version key |
| Product attributes | Approved item dimension | Sync-version key |

The route decision is logged and cannot be overridden by classifier text or narration.

## API execution

Replace generic model-driven calls on the v2 path with typed operations such as `get_item_stock`, `get_customer_outstanding`, and `get_order_status`. These operations may reuse transport/auth helpers from the existing factory.

Required behavior:

- one pooled async HTTP client per process;
- explicit connect/read/total timeouts;
- bounded retries only for safe transient failures;
- token refresh under a distributed-safe or acceptable process-local strategy;
- rate-limit handling and circuit breaker;
- response schema validation and numeric parsing with `Decimal`;
- explicit `complete`, `possibly_truncated`, or `page_limit_reached` status;
- pagination to a configured page and row ceiling;
- deduplication by documented upstream record key;
- mandatory source timestamp/freshness;
- sellable-status filtering only when the API contract exposes a verified status;
- no total when completeness cannot be proven.

If a live stock response lacks status or compatible piece-length semantics, fail the live check and offer the last-sync DB answer with a visible freshness downgrade. Do not guess.

## Computation, formatting, and narration

Use `Decimal` for currency and measured quantities. Define explicit rounding (`ROUND_HALF_UP` or the finance-approved rule), display precision, and null behavior.

The stock domain function receives already filtered pieces and returns a typed result:

```text
NO_STOCK
YES(longest_roll_m, total_m, pieces, qualifying_piece)
NO_SINGLE_PIECE(longest_roll_m, total_m, pieces)
```

The deterministic renderer is the guaranteed answer path for all v2 intents. Optional LLM narration is a cosmetic enhancement:

1. model receives only display-safe labels and precomputed raw/formatted values;
2. numeric/percentage/date tokens are checked against the payload allowlist;
3. causal language is rejected without an explicit decomposition fact;
4. after two failures, the deterministic renderer is used;
5. disclosure and interpretation are appended by code after narration, so the model cannot omit or alter them.

## Session state and aliases

Persist a `TurnRecord` server-side with:

- classifier output and schema version;
- resolved entities and picker choice;
- recipe/metric/registry version;
- normalized parameters and route;
- source and sync/API freshness;
- result reference, aggregates, row count, and completeness;
- rendered answer and validation attempts.

Store full rows only when necessary, encrypted, role-safe, and subject to a short retention/size limit. For larger results, store an immutable result reference or re-query parameters. A follow-up resolver reads structured turns, never assistant prose.

## Streaming and compatibility

Preferred v2 transport: one authenticated streaming POST implemented with `fetch` and a readable response stream. It removes the cross-instance race and avoids a JWT in the query string.

If EventSource must remain, use a durable job row plus Redis/Pub/Sub event channel and authenticate with a short-lived, single-use stream token. Do not use process-local queue ownership as the production boundary.

Add optional response fields:

- `interpretation`;
- `disclosure`;
- `source` and `freshness`;
- `confidence` and `fallback`;
- `resolution`/picker options;
- `completeness`;
- `turn_id` and versions.

Existing `summary`, `tables`, `charts`, and `execution_metadata` remain until all clients are migrated.

## Feature flags and rollback

Minimum controls:

- global `off | shadow | canary | on`;
- workspace allowlist;
- role allowlist;
- intent allowlist;
- API route kill switches;
- narration kill switch (deterministic template remains);
- fallback policy by role/intent;
- active registry and resolver versions.

Shadow mode computes v2 results without showing them. Do not double-call live APIs in shadow mode unless Incluziv approves the load; use captured fixtures or sampled calls. Rollback changes flags/pointers only—no destructive migration is required.
