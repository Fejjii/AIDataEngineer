# DE-ADR-011 — Workflow = state machine + phase-scoped task DAG

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1)

## Context
Workflows need adaptivity (discovery informs design informs generation), concurrency
(profiling many tables), auditability, resumability, and bounded loops.

## Decision
Two levels: a deterministic **workflow state machine** with an authoritative transition
table (`docs/STATE_MODEL.md` §3), and a **task DAG generated per phase** by the planner or a
deterministic phase template. The DAG is immutable inside a phase; dependencies cannot
cross phases; tasks are claimed with `FOR UPDATE SKIP LOCKED` and leased.

Each task carries a **stable operation identity** (`idempotency_key`, a function of
workflow, phase, local id, capability version and input digest — never of the attempt);
each execution try is a separate **attempt** record. Task state includes `PARKED` for
legitimate work that cannot run now (environmental denial, connector unavailable,
ambiguous non-idempotent outcome); the workflow parks in `BLOCKED` and resumes into the
phase it left. `POLICY_CHECK` routes by deny class (DE-ADR-015), not uniformly to `FAILED`.

## Alternatives
- Ordered task list: rejected (no parallelism, brittle).
- Whole-workflow static DAG: rejected (unknowable before discovery).
- Fully dynamic DAG with LLM-driven insertion: rejected (unbounded, hard to audit).

## Consequences
- Planner cost is paid only at phase boundaries; most phases use templates.
- Resume = reload state + reap leases + continue; no in-memory-only state.
- Adding a phase is a table + template change with tests, not an orchestrator rewrite.
