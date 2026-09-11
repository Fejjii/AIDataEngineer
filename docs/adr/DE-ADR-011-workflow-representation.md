# DE-ADR-011 — Workflow = state machine + phase-scoped task DAG

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1, DE 001R2A, DE 001R2B)

## Context
Workflows need adaptivity (discovery informs design informs generation), concurrency
(profiling many tables), auditability, resumability, and bounded loops.

## Decision
Three explicit levels: deterministic workflow state machine; persisted phase occurrence
(`phase_run_id`, monotonic generation, pinned contract snapshot); immutable task-template
DAG. Templates may contain unresolved references but have no operation identity. After
dependency outputs are immutable, input materialization resolves and validates all values,
persists canonical resolved-input digest, then computes the operation key including
`phase_run_id` and pinned capability/connector versions.

Each materialized task carries a stable `operation_idempotency_key`; each try is a separate
attempt. The key is stable across retries but distinct across legitimate repeated phase
runs. Policy, approval and attempts occur only after materialization. Task state includes `PARKED` for
legitimate work that cannot run now (environmental denial, connector unavailable,
ambiguous non-idempotent outcome); the workflow parks in `BLOCKED` and resumes into the
phase it left. `POLICY_CHECK` routes by deny class (DE-ADR-015), not uniformly to `FAILED`.

Runtime fan-out is forbidden inside an active phase. Discovery enumeration completes when
that phase run's accepted `Plan.phase_exit_criteria` are satisfied, then a new planning
boundary creates explicit sorted per-asset templates with unique `(phase_run_id, local_id)`.
A new planning boundary and a new phase occurrence allocate a `phase_runs` row; resume of
an existing PARKED or AWAITING_APPROVAL run does not. Phase reduction and advancement use a
transaction-scoped PostgreSQL advisory lock plus row/version and uniqueness checks.
Required dependency failure is exhaustively propagated; no dependant may remain pending
indefinitely.

Cancellation is intent plus controlled shutdown (`CANCEL_REQUESTED`, `CANCELLING`).
Terminal `CANCELLED` requires quiescence or explicit durable parking of unresolved effects.

## Alternatives
- Ordered task list: rejected (no parallelism, brittle).
- Whole-workflow static DAG: rejected (unknowable before discovery).
- Fully dynamic DAG with LLM-driven insertion: rejected (unbounded, hard to audit).

## Consequences
- Planner cost is paid only at phase boundaries; most phases use templates.
- Resume = reload state + reap leases + continue; no in-memory-only state.
- Adding a phase is a table + template change with tests, not an orchestrator rewrite.
