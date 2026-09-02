# DataLens v2 deterministic rebuild

Status: proposed implementation baseline

Repository baseline: `d20a320` on `feat/datalens-v2`

Reviewed: 02 Sep 2026

This folder translates the two approved research documents into a repository-specific delivery plan. It is intentionally documentation-only: no application behavior, database object, deployment setting, or user flow has been changed.

## Source material reviewed

- [`DataLens Deterministic Rebuild Tech Spec v1.1`](../../DataLens%20Deterministic%20Rebuild%20Tech%20Spec%20v1.1.docx) — authoritative proposed rules, data model, routing, acceptance criteria, and open items.
- [`DataLens Remediation Summary v1.3`](../../DataLens%20Remediation%20Summary%20v1.3.docx) — defect evidence, question catalogue, rationale, and expected user behavior.
- Current backend, frontend, tests, deployment scripts, load test, and persistence schema in this repository.
- Existing `data/agentic_accuracy_report.xlsx` and `data/agentic_bucket_report.xlsx`. These are application datasets, not the 70-question evaluation workbook named by the specification.

The detailed resolver design supplied with the request is treated as a refinement of Technical Specification §3. Where it conflicts with the earlier single-table `resolver_index`, the entity/postings model is recommended, subject to the decisions in the risk register.

## Documents in this pack

1. [Repository R&D and gap analysis](./REPOSITORY_RND_AND_GAP_ANALYSIS.md) — what exists, what is reusable, what conflicts with the proposal, and what is not yet verified.
2. [Target architecture](./TARGET_ARCHITECTURE.md) — component boundaries, runtime flow, storage placement, tenancy, resolver, registry, API handling, and backward compatibility.
3. [Implementation roadmap](./IMPLEMENTATION_ROADMAP.md) — phased work, dependencies, deliverables, acceptance gates, rollout, and rollback.
4. [Test, audit, and production-readiness plan](./TEST_AUDIT_AND_ROLLOUT.md) — validation matrix, evaluation harness, security testing, observability, scale testing, and release evidence.
5. [Decision and risk register](./DECISION_AND_RISK_REGISTER.md) — limitations and unresolved decisions to relay to the DataLens, ERP sync, Incluziv, security, and product teams.
6. [Specification traceability](./SPEC_TRACEABILITY.md) — maps every source-specification area to planned components, tests, and gates.

## Recommended decision

Proceed with the deterministic rebuild, but do not implement it as a replacement of the current agent loop. Build it beside the existing path and promote one intent at a time only after its data contract and golden tests pass.

The first release gate is not the resolver or classifier. It is:

1. authorize every workspace and connection server-side;
2. establish a reliable single-request or shared-broker streaming path;
3. validate production data and canonical metric definitions;
4. obtain the missing evaluation corpus and registry asset;
5. then enable deterministic intents behind flags.

This ordering protects existing users while the v2 path is proved against real traffic.

## Non-negotiable v2 invariants

- The primary path never accepts model-generated SQL.
- The model never calculates or formats a displayed number.
- All user-derived values are bound parameters; identifiers come from allowlists.
- Customer scope is derived from authenticated server context and enforced below orchestration.
- Business queries use approved semantic views, not raw synced tables.
- Live-source truncation is never presented as a complete total.
- Quantitative follow-ups use structured state or re-query; prior prose is not data.
- Every quantitative response identifies interpretation, scope, metric, period, freshness, and exclusions.
- Unsupported or unsafe cases fail clearly; they do not silently broaden.
- Every rollout step is reversible without deleting or rewriting v1 data.

## Current verification status

- Both DOCX files were read in full.
- The tracked repository and all local branches were searched for a metric registry, resolver, migrations, and evaluation harness. None is present in this checkout.
- The active Python environment cannot run the backend suite because `pytest` is not installed.
- The frontend verification environment is not bootstrapped: `npm run build` used an incompatible/global TypeScript installation and could not find local Vite/Node types; `npm run lint` could not find ESLint.
- No production ERP/analytics database or live Incluziv endpoint was queried. All data-discovery claims from the source documents remain externally supplied evidence until Phase 0 captures reproducible results.

These are environment and evidence gaps, not reasons to discard the proposed architecture. They are explicit prerequisites in the roadmap.
