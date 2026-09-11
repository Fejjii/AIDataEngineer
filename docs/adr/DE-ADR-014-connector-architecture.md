# DE-ADR-014 — Connector protocol with real + fake implementations and status

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1, DE 001R2A)

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

Every connector advertises supported contract/schema versions and receives materialized
immutable input. Side-effecting handlers propagate operation and attempt identities.
`reconcile(RecoveryContext)` receives resolved-input digest/schema, pinned
capability/connector versions, target, attempt/provider refs and operation locators.
Results are `EffectFound | NoEffect | InProgress | Unknown`; `InProgress` is bounded and
never treated as absence. This applies to every ambiguous failure, not only lease expiry.

Health is a typed TTL-bound snapshot with missing permission values. Temporary
unavailability parks execution but does not invalidate a structurally valid plan.
Connector artifacts carry transitive REAL/MOCK provenance; real Git/deploy denies MOCK
ancestry. Snowflake read capabilities use a separate RO identity and canonical round-trip
query tags with full operation and attempt ids. dbt writes use invocation journals and
default to non-idempotent unless convergence is proven per materialized input.

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
