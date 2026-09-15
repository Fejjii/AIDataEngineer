# Architecture Decision Records

Product architecture ADRs for the AI Data Engineer platform. Numbering continues from the
operating-system ADRs in `.ai/DECISIONS.md` (DE-ADR-001..007). Each ADR here also has a
compact entry in `.ai/DECISIONS.md`; this directory holds the full record.

Status values: PROPOSED · ACCEPTED · SUPERSEDED · REJECTED.

| ADR | Title | Status |
|---|---|---|
| [DE-ADR-008](DE-ADR-008-modular-monolith.md) | Modular monolith application architecture | ACCEPTED |
| [DE-ADR-009](DE-ADR-009-custom-orchestration.md) | Custom deterministic orchestration; no agent framework | ACCEPTED |
| [DE-ADR-010](DE-ADR-010-agent-strategy.md) | Single orchestrator with reasoning capabilities; no specialist agents | ACCEPTED |
| [DE-ADR-011](DE-ADR-011-workflow-representation.md) | Workflow = state machine + phase-scoped task DAG | ACCEPTED |
| [DE-ADR-012](DE-ADR-012-state-persistence.md) | PostgreSQL + SQLAlchemy 2 + Alembic for all state | ACCEPTED |
| [DE-ADR-013](DE-ADR-013-capability-abstraction.md) | Capability / tool / connector abstraction | ACCEPTED |
| [DE-ADR-014](DE-ADR-014-connector-architecture.md) | Connector protocol with real + fake implementations and status | ACCEPTED |
| [DE-ADR-015](DE-ADR-015-deterministic-policy.md) | Deterministic policy engine and SQL safety classifier | ACCEPTED |
| [DE-ADR-016](DE-ADR-016-approval-system.md) | Typed approval subjects with complete binding | ACCEPTED |
| [DE-ADR-017](DE-ADR-017-llm-abstraction.md) | Thin LLM gateway, structured outputs, versioned prompts | ACCEPTED |
| [DE-ADR-018](DE-ADR-018-observability.md) | Observability: audit, telemetry tables, OpenTelemetry, structlog | ACCEPTED |
| [DE-ADR-019](DE-ADR-019-evaluation.md) | In-repo evaluation harness; no LLM judge for pass/fail | ACCEPTED |
| [DE-ADR-020](DE-ADR-020-local-vs-cloud-development.md) | Local vs Cloud development boundaries for product work | ACCEPTED |
| [DE-ADR-021](DE-ADR-021-parallel-development.md) | Parallel development lanes and unlock milestones | ACCEPTED |
| [DE-ADR-022](DE-ADR-022-background-execution.md) | In-process worker with PostgreSQL task queue | ACCEPTED |
| [DE-ADR-023](DE-ADR-023-bounded-repair.md) | Bounded self-repair loop | ACCEPTED |
| [DE-ADR-024](DE-ADR-024-frontend.md) | Minimal Vite + React + TypeScript SPA | ACCEPTED |
| [DE-ADR-025](DE-ADR-025-python-toolchain.md) | Python 3.12, uv, ruff, mypy strict, pytest | ACCEPTED |
| [DE-ADR-026](DE-ADR-026-contract-stability.md) | Contract stability: baseline in DE 002, compatible evolution afterwards | ACCEPTED |
| [DE-ADR-027](DE-ADR-027-trusted-principal-and-grants.md) | Trusted local principal and server-authorized workflow grants | ACCEPTED |
| [DE-ADR-028](DE-ADR-028-interview-mvp-boundary.md) | Constrain the active roadmap to one Interview MVP closed loop | ACCEPTED |

Amended by DE 001R1 (2026-09-11): DE-ADR-011 (operation vs attempt identity, `PARKED`),
DE-ADR-014 (`allowed_permissions`, `reconcile`), DE-ADR-015 (permission sets, denial
routing), DE-ADR-016 (approval bound to operation identity), DE-ADR-022
(reconcile-before-retry), DE-ADR-024 (wording).

Amended by DE 001R2A (2026-09-11): DE-ADR-011, 013–018, 021, 022 and 026; added
DE-ADR-027. Changes harden materialization identity, phase serialization, fencing,
ambiguous reconciliation, policy aggregation, typed approvals, trusted grants, versioning
and DE 002 sequencing without changing the modular-monolith thesis.

Amended by DE 001R2B (2026-09-11): DE-ADR-011 (phase-run exit criteria and resume vs new
occurrence), DE-ADR-014 (`identity_class` and READ_ONLY warehouse binding), DE-ADR-015
(scheduler-emitted `CONTRACT_VERSION_UNAVAILABLE`), DE-ADR-016 (approval rejection
transitions), DE-ADR-020 (DE 002A CLOUD; DE 002B/C LOCAL), DE-ADR-022 (lock scope and
exhausted `NoEffect` failure).

Accepted by operator (2026-09-11): DE-ADR-008 through DE-ADR-027 status set to ACCEPTED.

Amended by OPS004 (2026-09-11): DE-ADR-020 — OPS002 assessed remote development readiness;
OPS003 implemented and validated the Cursor Cloud environment; operator saved the environment;
fresh Cloud Agent verification passed; DE 002B and DE 002C reclassified from LOCAL to CLOUD.
Credential boundaries unchanged (real Snowflake, live dbt on Snowflake, live staging,
production, and secret entry remain LOCAL or Hybrid per existing gates).

Accepted with PIVOT001 (2026-09-14): DE-ADR-028 supersedes DE-ADR-021 as the active
implementation ordering. It preserves completed DE002–DE008A work and constrained
implementation to MVP001–MVP004, now merged to `main`.
