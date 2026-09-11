# DE-ADR-014 — Connector protocol with real + fake implementations and status

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1)

## Context
The system must be testable and demonstrable without production credentials, simulate
failures, and expose honestly whether an integration is real.

## Decision
Stable `Connector` protocol (`docs/CONNECTOR_ARCHITECTURE.md` §2). Every connector ships a
real implementation, a deterministic fake with fault injection, a vendor error → failure
class mapper, configuration with `SecretRef` only, contract tests parametrized over
fake/real, and a README. Connector instances are bound to exactly one environment and
carry an explicit `allowed_permissions` set (membership-checked, no ordering — DE 001R1
replaced the earlier "permission ceiling") and an object allow-list. Product-visible status
`AVAILABLE | DEGRADED | UNAVAILABLE | MOCK`; `UNAVAILABLE` parks dependent tasks rather
than failing them.

Every connector implements `reconcile(capability_id, idempotency_key, ctx)` for its
side-effecting capabilities and propagates the operation identity into the external system
(query tag, provenance comment, commit trailer, PR head branch, release id), so the
scheduler can recover a crashed attempt without repeating the effect
(`docs/STATE_MODEL.md` §4.6). Fakes implement `reconcile` and `fail_after_effect`.

Warehouse fakes use DuckDB with sqlglot transpilation; dbt fake executes generated SQL
against the fake warehouse; GitHub fake uses a local bare repository.

## Alternatives
- Mocks per test only (no shared fake): rejected — no offline demo, no CI scenarios.
- Recording/replay of vendor calls only: partially adopted for error mappers; insufficient
  alone because the demo needs dynamic behaviour.

## Consequences
- Some Snowflake-specific SQL will not run in DuckDB; generation conventions favour
  portable SQL and fakes mark unsupported features explicitly.
- Fakes are first-class code with tests, not throwaway.
