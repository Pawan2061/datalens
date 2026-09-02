# Specification traceability

This matrix prevents requirements from disappearing between research and implementation. Status values are `not started`, `blocked`, `partial in v1`, or `planned`; this documentation task does not mark application work complete.

| Source requirement | Repository evidence | Planned implementation/evidence | Status |
|---|---|---|---|
| Tech §0: model only classifies and words | Current ReAct model selects tools and writes SQL | Typed classifier + registry compiler + optional validated narration | Planned |
| Tech §0: shared metric definition | No registry found in tracked refs | `MetricRegistry` port; import existing asset or create approved registry | Blocked on D-06 |
| Tech §1.1: duplicate recurrence | No post-sync assertion job in repo | Alert-only assertion; source-line key decision before unique index | Blocked on D-02 |
| Tech §1.2: post-dedup reconciliation | No production evidence in repo | Versioned Phase 0 report using line taxes and residual buckets | Blocked on D-01 |
| Tech §1.3: line taxes only | Current prompt uses header tax totals | Canonical semantic view/metric; remove header tax use from v2 | Planned |
| Tech §1.4: nightly assertions | No job/migrations/runbook | Post-sync locked job, persisted results, alert/runbook, seven-night gate | Planned |
| Tech §2.1: line view/canonical revenue/swatch | No view | Validated source migration and control-total tests | Planned, D-03/D-04 |
| Tech §2.2: header view | No view; invoice identity unproven | True document key, consistency gate, header-only metrics | Blocked on D-02 |
| Tech §2.3: stock views | No view | Sellable/all views and status-distribution assertion | Planned, D-09 for API |
| Tech §2.4: item namespace | No semantic item dimension | Expose only `item_category`; registry rejects ambiguous `collection` | Planned, D-05 |
| Tech §3 + detailed resolver: index | Runtime SQL/prose resolution | Source-scoped entity/token generations and alias store | Planned |
| Resolver normalization | No shared normalizer | One build/query normalizer with golden cases | Planned |
| Resolver scoring/policy | Prompt-driven clarification | Bounded/versioned scoring, deterministic policy, picker | Planned |
| Resolver aliases | None | Scoped evidence, reviewed promotion, revoke/audit | Planned |
| Tech §4.1: classifier JSON/defaults | Security classifier only | Complete business intent schema, repair retry, code defaults | Planned |
| Catalogue Q1–Q9 | No deterministic intent catalogue | One end-to-end vertical slice and DoD per intent | Planned |
| Tech §4.2: registry templates | Raw SQL tool | Allowlisted recipes, bound values, schema validation | Planned |
| Tech §4.3: API/DB routing | Model chooses dynamic tools | Pure post-resolution route policy | Planned |
| Tech §4.4: tenancy | Server scope + regex backstop | Request context, authorization, constructed predicates, DB controls | Partial in v1; security blocker |
| Tech §5.1: code computation | API totals/maxes partially computed; model still selects/calculates | Typed metric aggregators and locked payload | Partial in v1 |
| Tech §5.2: INR formatter | Float annotation + limited tests | Decimal formatter, corrected golden set, finance sign-off | Partial in v1; D-15 |
| Tech §5.3: roll rule | Max supplied to prompt | Pure state-returning domain function + recorded fixtures | Partial in v1 |
| Tech §5.4: disclosure | No structured mandatory disclosure | Backend-generated interpretation/disclosure fields | Planned |
| Tech §5.5: narration validator | Prompt instruction only | Numeric/date allowlist, causal validation, template fallback | Planned |
| Tech §5.6: session state | Client sends condensed prose | Server-owned `TurnRecord`, result reference, re-query policy | Planned |
| Tech §5.7: cache | Question-normalized in-memory cache | Versioned canonical key; volatile intents disabled | Partial in v1 |
| Tech §6.1–6.2: API cursor/cap | No pagination/completeness contract | Typed pagination and `possibly_truncated`; suppress partial total | Blocked on D-08 |
| Tech §6.3: live stock | Generic API tool exists | Typed stock operation, verified mapping/filter, roll function | Blocked on D-09 |
| Tech §6.4: multi-customer outstanding | No reliable DB route | Explicit parked result; no API fan-out | Parked on D-10 |
| Tech §7: fallback/learning loop | Full v1 agent and limited analytics logging | Risk-gated fallback, AST/role controls, weekly report, eval promotion | Planned |
| Tech §8: telemetry | Cost/timing/row analytics only | Full turn event with privacy/retention controls and dashboards | Partial in v1 |
| Tech §9: open items | No tracked decision log | D-01 through D-17 in risk register | Tracked |
| Tech §10: acceptance | No v2 release gate | CI/eval/security/performance/release evidence checklist | Planned |
| Remediation §2–3: select architecture | Current generate architecture | `datalens_v2` strangler package and feature flags | Planned |
| Remediation §4 A1–A7 | Some prompt mitigations only | Phase 0/1 data contract and disclosures | Planned/blocked as above |
| Remediation §4 B1–B4 | Prose schema and incorrect revenue prompt | Semantic views, registry, qualified dimensions/defaults | Planned |
| Remediation §4 C1–C2 | Runtime fuzzy probing possible | Resolver and policy | Planned |
| Remediation §4 D1–D4 | Question cache/prose history/API cap/regex scope | Version cache/state/API completeness/tenancy architecture | Partial in v1 |
| Remediation §4 E1–E4 | Prompt + annotations, no validator/disclosure | Typed assembly, formatter, roll function, disclosure, validator | Partial in v1 |
| Remediation §5: Hinglish and variety | Prompt-level language handling | Tagged classifier/resolver/narration evaluation | Planned |
| Remediation §6: question catalogue | No recipe catalogue | Registry recipes and routing matrix by Q1–Q9 | Planned |
| Remediation §7: sequencing | No v2 implementation | Phases -1 through 6 in roadmap | Planned |
| Remediation §8: success | No frozen-source deterministic harness | Evaluation and production acceptance in test plan | Blocked on D-07 |
| Production non-disruption constraint | V1 is live path | Additive schema/API, flags, shadow, canary, kill switch, no destructive cutover | Planned |
| Production scale constraint | Process-local streams/caches/jobs | Streaming topology, distributed scheduling, pooling, load/SLO gates | Planned |
| Audit/test constraint | Toolchain not bootstrapped in current environment | Reproducible CI baseline and evidence bundle per rollout | Planned |

## Coverage rule

Every implementation pull request must reference one or more rows in this matrix, update its status, link test evidence, and state rollback impact. New requirements get a row before implementation.
