# DE-ADR-013 — Capability / tool / connector abstraction

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R2A)

## Context
The orchestrator must reason about *what* to do, not *which vendor*; new platforms must
not change the core; every operation must be typed, permissioned, validated and audited.

## Decision
- **Capability** = immutable typed contract (`CapabilitySpec`, `docs/CAPABILITY_MODEL.md`).
- **Tool** = binding of a capability to an implementation (connector handler or reasoner),
  wrapped by the Tool Registry which enforces validation → policy → timeout → validation →
  audit for every call.
- **Connector** = adapter to one external system advertising the capabilities it implements.
Reasoning capabilities are catalogued with the same discipline (typed I/O, validators,
cost accounting) and can never have external effects.

Connectors advertise supported capability contract plus input/output schema versions.
Each phase run pins a stable contract snapshot; in-flight work continues on pinned
implementations or parks if unavailable, never silently upgrading JSON payloads.
`CapabilitySpec` uses invocation effect semantics rather than a capability-level
`idempotent` boolean.

Shared asset addresses and SQL dialect ids are extensible strings/hierarchies. Generic
transformation plans/results are separate from versioned dbt extension payloads, so the
orchestrator does not depend on dbt concepts.

## Alternatives
- Vendor-specific tools exposed to the planner (`snowflake_run_sql`): rejected — vendor
  logic leaks into planning and policy.
- Free-form "function calling" over SDK methods: rejected — unbounded surface.

## Consequences
- Adding a warehouse = implementing ~9 handlers + fake + tests, no orchestrator change.
- Capability changes are versioned and need an ADR when incompatible.
