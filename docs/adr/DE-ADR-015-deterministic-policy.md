# DE-ADR-015 — Deterministic policy engine and SQL safety classifier

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1, DE 001R2A, DE 001R2B)

## Context
Critical policy must not live only in prompts. Generated SQL must not cause unsafe
mutations. The LLM must not be able to grant itself authority.

## Decision
A pure-function `PolicyEngine` with deterministic rules (R0 at startup, runtime rules in
`docs/PERMISSION_MODEL.md` §3) evaluated for every capability call inside the Tool
Registry, persisted before execution, fail-closed. A sqlglot-based `classify_sql`
capability provides statement types, object scope, destructive/dynamic/multi-statement
flags; unparseable SQL is classified destructive. Defence in depth with identities and
namespaces.

**Permissions are a set, not a ladder (DE 001R1).** `PermissionLevel` has one canonical
definition (`aide.domain.permissions`), nine distinct grants and **no ordering**. A
capability requires one permission; a workflow holds a grant set; a connector instance
holds an `allowed_permissions` set. Every check is set membership (`required ∈ grants ∪
approval-covered`, `required ∈ connector.allowed_permissions`); "ceilings", numeric ranks
and `<`/`>` comparisons are forbidden and tested against.

**Denials are routed by class (DE 001R1).** Every reason code maps to exactly one deny
class — `ENVIRONMENTAL` (operator-resolvable: connector unavailable, secret unresolved,
missing connector permission) → task `PARKED`, workflow `BLOCKED`; `SCOPE` and `SECURITY`
(permission not granted, scope/namespace/environment violation, unsafe SQL, protected
branch, secret in diff) → task `FAILED`, workflow `FAILED`, fail closed, audit alert for
`SECURITY`. Approval-eligible operations (`STAGING_DEPLOY`, `DESTRUCTIVE` in DEV, ALWAYS-
approval capabilities, cost, design flags) → `APPROVAL_REQUIRED`. The mapping is data with
an exhaustiveness test (`docs/PERMISSION_MODEL.md` §3.1). The plan validator runs the same
rules as a pre-check so that the planner can re-plan *before* tasks exist; once a task
exists there is no routing around a denial.

**Aggregate every denial (DE 001R2A).** Runtime evaluation executes every applicable deny
rule and persists all reason codes. Rule order cannot change the result.
`SECURITY > SCOPE > ENVIRONMENTAL` is the authoritative routing severity, so security
alerts cannot be masked. Approval requirements are evaluated only when no denial exists
and are returned as a complete set.

Policy accepts only trusted `PrincipalRef` and server-derived `GrantAuthorization`; clients
may request but cannot set effective grants. Connector health is a typed fresh snapshot.
Plan validation is structural and independent of temporary health. SQL safety uses RO
identities for reads, dialect round-trip parsing, canonical scope, safe function/construct
classification, and denial of external/unknown functions, stages/URLs and unknown nodes.
MOCK provenance cannot enter real Git/deploy. The scheduler, not a payload rule, emits
`CONTRACT_VERSION_UNAVAILABLE` when a pinned handler is missing; routing stays
`ENVIRONMENTAL`.

## Alternatives
- Prompt-level guardrails only: rejected — bypassable, untestable.
- LLM-based safety judge: rejected — non-deterministic, circular.
- Regex-only SQL filtering: rejected — brittle; kept only as an additional heuristic.

## Consequences
- Property-based and adversarial tests are mandatory for the classifier and policy.
- Adding a permission means adding it to the relevant connector sets explicitly; nothing is
  inherited. Adding a reason code without a deny-class mapping fails the test suite.
- `CONNECTOR_UNAVAILABLE` and `POLICY_CHECK` no longer contradict each other: the former
  parks, the latter routes by class.
- Some legitimate statements will be denied (e.g., Snowflake-specific syntax sqlglot
  cannot parse) → generation conventions and a curated allow-list of functions.
