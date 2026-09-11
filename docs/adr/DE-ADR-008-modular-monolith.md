# DE-ADR-008 — Modular monolith application architecture

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001

## Context
The platform has ~28 logical components (`docs/ARCHITECTURE.md` §3). It must be
testable offline, resumable, auditable, demonstrable by one engineer, and extensible to
new connectors without core changes. Demo scale is ≤ 5 concurrent workflows.

## Decision
One Python package (`aide`), one deployable image, one PostgreSQL database. The API and
the task worker run in the same process by default and can be started as separate
processes of the same image. Component boundaries are enforced by module layout, typed
interfaces, and `import-linter` contracts — not by network boundaries.

## Alternatives
- **Microservices** (orchestrator, connectors, policy as services): rejected — operational
  cost, distributed transactions across workflow state, no scaling need in V1.
- **Serverless functions per capability**: rejected — cold starts for dbt/Snowflake
  sessions, harder local/offline testing.
- **Kubernetes from day one**: rejected — no multi-node requirement.

## Consequences
- Fast local loop; the whole system runs with `docker compose up`.
- Later extraction of the worker or connectors into services is possible because
  boundaries already exist in code.
- Single database is a shared dependency; mitigated by clear table ownership (§8 of the
  architecture).
