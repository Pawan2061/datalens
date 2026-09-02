# Decision and risk register

This is the relayable list for team review. `BLOCKER` means the affected capability must not ship until resolved. `HIGH` means implementation can start behind flags, but customer exposure cannot.

## Decisions required

| ID | Priority | Owner | Decision/evidence needed | Blocks |
|---|---|---|---|---|
| D-01 | BLOCKER | Data/ERP | Publish Phase 0 post-dedup reconciliation using authoritative line taxes and explain residuals. | Semantic-layer sign-off |
| D-02 | BLOCKER | Data/ERP | Confirm full tenant/company/branch/FY invoice identity and source line identity/idempotency key. | Header view, duplicate prevention |
| D-03 | BLOCKER | Product/Data | Sign the canonical revenue label and formula; confirm whether `order_amt` is pre/post discount. | All sales metrics |
| D-04 | HIGH | Product/Data | Confirm complete swatch identification and whether all sales defaults exclude it. | Sales recipe release |
| D-05 | HIGH | Product/Data | Confirm `invoice.collection` is sales authority and define `item_category` usage. | Collection grouping |
| D-06 | BLOCKER | Insight team | Provide the existing metric registry repository/schema/API and ownership, or approve a new registry here. | Shared chat/insight metrics |
| D-07 | BLOCKER | QA/Product | Provide the 70-question workbook and 12 contradiction transcripts with expected outcomes. | Release evaluation gate |
| D-08 | BLOCKER | Incluziv | Confirm cursor/`LAST_ID`, stable ordering, end marker, cap behavior, rate limits, and snapshot semantics. | Complete outstanding/order totals |
| D-09 | BLOCKER | Incluziv/Data | Confirm stock piece-length field/unit/precision and sellable-status field/filter. | Live roll availability |
| D-10 | BLOCKER | Data/Product | Locate/profile the daily outstanding table and decide the multi-customer source. | Multi-customer outstanding only |
| D-11 | HIGH | Security/Platform | Approve tenant isolation design: application injection plus restricted role and RLS/security views where feasible. | Customer canary |
| D-12 | HIGH | Platform | Choose single-request streaming or shared broker; choose scheduler lease/external scheduler. | Multi-instance scale |
| D-13 | HIGH | Product/Security | Approve fallback by role/intent. Recommended: no freehand customer financial/stock/outstanding answers. | Fallback release |
| D-14 | MEDIUM | Product/UX | Approve interpretation, picker, disclosure, freshness, completeness, and low-confidence UI copy. | Non-technical-user acceptance |
| D-15 | MEDIUM | Finance/Data | Correct the ambiguous `1,219 Cr` formatter example and approve Decimal rounding. | Formatter golden tests |
| D-16 | MEDIUM | Legal/Security | Define question/result/alias/telemetry retention, encryption, access, export, and deletion. | Structured-state production use |
| D-17 | MEDIUM | Engineering | Choose the supported frontend package manager and Python lock strategy. | Reproducible CI |

## Risk register

| ID | Severity | Risk/limitation | Evidence in current repo/spec | Mitigation and exit criterion |
|---|---|---|---|---|
| R-01 | Critical | Cross-workspace connection access | Connection routes have no auth dependency; chat accepts submitted workspace/connection IDs without association check. | Central authorization dependency; negative HTTP tests for every role/route. |
| R-02 | Critical | SSE fails or loses events across instances | POST/GET coordinate through process-local dictionaries; Cloud Run allows 3 backend instances. | One-request authenticated stream or shared broker; multi-instance test green. |
| R-03 | Critical | Tenant filter bypass | Current enforcement is regex over raw table names and will not cover proposed views reliably. | Construction-time scope, restricted DB role/RLS, AST fallback validation, cross-tenant canary tests. |
| R-04 | Critical | Canonical revenue remains wrong during partial migration | Current prompt explicitly uses unreliable header tax totals. | Never enable v2 sales until view/registry control totals pass; keep definitions versioned once. |
| R-05 | Critical | Capped API page is presented as total | Existing API adapter totals every received row but cannot prove upstream completeness. | Typed completeness state; pagination contract; suppress totals when unknown. |
| R-06 | High | Multi-customer outstanding is fabricated by fan-out | Reliable DB source is unknown and API caps at 300. | Keep parked; explicit per-customer UX only. |
| R-07 | High | Live stock includes non-sellable rows or wrong unit | API mapping/filter not confirmed. | Contract test; fail or disclosed last-sync fallback until verified. |
| R-08 | High | Duplicate guard deletes/blocks legitimate lines | Candidate key and count/distinct detector collide with valid identical piece lines. | Alert-only detector; require upstream source-line/idempotency key before unique constraint. |
| R-09 | High | Header view masks inconsistent invoice data | Sample view uses `MAX`, which can pick one of conflicting header values. | Phase 0 zero-violation gate; quarantine/fail invalid documents; use true document key. |
| R-10 | High | Resolver silently chooses wrong entity | Thresholds are uncalibrated; proposed specificity formula is not bounded; 12,585 numeric collisions. | Labeled evaluation, bounded score, conservative ask policy, stable tie-break, picker override monitoring. |
| R-11 | High | Alias poisoning/cross-tenant leakage | Proposal learns picker choices; a global alias could encode one user's ambiguous choice. | Scope aliases; reviewed promotion; audit/revoke; security tests. |
| R-12 | High | Freehand fallback restores the same failure mode | Proposed fallback still lets an LLM write SQL and can contradict hard-failure principle. | Risk-based role/intent allowlist; internal-only first; AST, views, scope, timeout, low-confidence UI. |
| R-13 | High | Stale or cross-version cached answers | Current cache is question-normalized, process-local, and lacks sync/registry version. | Canonical parameter key; source/recipe version; volatile cache off. |
| R-14 | High | Quantitative follow-up comes from prose | Client submits condensed narratives; no structured server turn state. | Persist typed turn state; re-query/result reference requirement. |
| R-15 | High | Generic numeric aggregation corrupts identifiers | Existing API adapter sums/maxes every numeric-looking column. | Metric-specific typed aggregators and API schemas. |
| R-16 | High | SQL timeout/row cap does not fully constrain work | Client-side timeout and `fetchmany` do not guarantee database resource limit or completeness signal. | Server statement timeout, read-only transaction, `LIMIT N+1`, bytes/rows budget, cancellation test. |
| R-17 | High | Scheduled jobs duplicate on autoscale | Scheduler starts in every app instance. | External scheduler or distributed lease/advisory lock. |
| R-18 | High | Missing registry/eval assets cause guessed implementation | Neither asset is present in tracked refs. | Resolve D-06/D-07; adapter interfaces allow safe preparatory work only. |
| R-19 | Medium | Monetary precision/rounding drift | Existing formatter converts through `float`; specification has an inconsistent expected example. | `Decimal`, explicit rounding, signed golden fixtures. |
| R-20 | Medium | Resolver rebuild briefly exposes partial/mixed data | Simple truncate/rebuild or rename can race readers and permissions. | Versioned generations + atomic active pointer + retained rollback generation. |
| R-21 | Medium | Trigram/prefix work becomes slow at scale | 0.35 is unmeasured and index behavior not benchmarked. | Query-plan/load benchmarks at representative postings count and typo mix. |
| R-22 | Medium | Hinglish/typo accuracy is assumed | No classifier/resolver multilingual test suite exists in checkout. | Tagged evaluation set and language-segmented metrics. |
| R-23 | Medium | Telemetry creates a privacy store | Proposed logging includes questions, SQL, results, candidate names, and final answers. | Minimize/redact/encrypt, role-gate access, retention/deletion policy. |
| R-24 | Medium | Dynamic API transport permits SSRF variants | Existing check covers common textual private IPv4 hosts but not all DNS/redirect/IPv6/metadata cases. | Resolve and validate addresses, HTTPS/host allowlist, redirect policy, egress controls. |
| R-25 | Medium | Health checks remain falsely green | Current health endpoint does not test source/registry/sync/API readiness. | Liveness separate from dependency readiness; per-source degradation dashboard. |
| R-26 | Medium | Runtime migrations race or overprivilege app | Persistence tables are created at startup; source DDL rights are available. | Separate migration identity, migration job, SELECT-only runtime role. |
| R-27 | Medium | Existing behavior breaks during cutover | Current UI/session/export expect `InsightResult` and current SSE events. | Additive response schema, adapter events, workspace/intent flags, shadow and canary. |
| R-28 | Medium | “Three identical answers” fails for valid live changes | Global acceptance does not distinguish frozen DB data from changing APIs. | Freeze fixtures/version for repeatability; live tests assert rules, completeness, and freshness. |
| R-29 | Medium | Results retained in sessions exceed privacy/size limits | Proposal permits up to 500 rows per turn without retention rules. | Store references/aggregates by default; bounded TTL/encryption and size budgets. |
| R-30 | Medium | API client overhead and upstream pressure at scale | Current adapter creates a new async client per call and has no route-specific circuit breaker. | Pooled client, concurrency budget, rate handling, backoff, circuit metrics. |

## Recommended policy decisions

Unless a business owner overrides them explicitly:

- Use the refined entity/postings resolver, scoped by source and generation.
- Default to asking rather than auto-acting when a wrong entity changes money, stock, or customer identity.
- Do not globally learn aliases from one picker choice.
- Use no response cache for stock, outstanding, or order status.
- Disallow customer-facing freehand SQL for money, availability, outstanding, and other-customer questions.
- Treat an exactly-300 API response as possibly truncated until upstream proves otherwise.
- Use last-sync stock only as an explicit degraded answer when live status/length semantics are unavailable.
- Make deterministic templates the primary response; LLM narration is optional.
- Keep v1 and v2 storage additive until the rollback window closes.
- Use the phrase `net sales before GST, after line discount, gross of returns` until finance approves a better label.

## Team-ready limitation statement

DataLens v2 can make the observed question types deterministic, but it cannot manufacture source completeness. Returns are absent, multi-customer outstanding has no approved source, live API pagination and stock semantics are not confirmed, and duplicate prevention lacks a reliable source-line identity. Those limitations must be disclosed or the affected feature withheld. The repository also needs authorization and multi-instance streaming fixes before a production-scale customer rollout. The rebuild should therefore ship by verified intent behind flags, not as one all-at-once replacement.
