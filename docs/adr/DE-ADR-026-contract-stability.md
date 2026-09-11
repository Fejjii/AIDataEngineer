# DE-ADR-026 — Contract stability: baseline in DE 002, compatible evolution afterwards

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001R1

## Context
The first architecture draft "froze" every core interface at DE 002. That would fix field
lists before the Snowflake (DE 005) and dbt (DE 008) integrations had exercised them, and
would force an ADR for harmless additions such as a new optional field, reason code or
telemetry column. At the same time, cheaper implementation models must not silently change
contracts other tasks depend on.

## Decision
DE 002 establishes the **architecture baseline** for the core contracts listed in
`docs/IMPLEMENTATION_PLAN.md` §5.2 (`PermissionLevel`, `CapabilitySpec`, connector
protocol, policy request/decision, task and attempt records, transition table, artifact
refs, LLM gateway types, audit and telemetry rows, settings, CLI names).

- **Breaking changes** — removing or renaming fields, changing types or semantics, making
  optional fields required, removing enum members or reason codes, changing existing
  transitions or guards, incompatible capability schema changes — require an ADR in
  `docs/adr/`, an entry in `.ai/DECISIONS.md`, and architecture review by a higher-tier
  model before merge. Transition-table and permission-model changes are always breaking.
- **Additive, backward-compatible changes** — new optional fields with defaults, new enum
  members or reason codes handled by consumers' default branches (and added to the
  deny-class map), new capabilities, rules, validators, CLI commands, telemetry columns —
  are allowed inside the implementing task **when every existing test remains valid and
  passes unchanged**; they are described in the PR and mirrored into `docs/` in the same PR.
- **Internal changes** behind the contract need only normal review.

Contracts are considered *exercised* once DE 005 and DE 008 have merged (Wave 2); additive
adjustments discovered there are expected and do not require an ADR.

## Alternatives
- Freeze every field at DE 002: rejected — premature; would either block DE 005/DE 008 or
  be ignored in practice.
- No policy (ordinary code review only): rejected — parallel Cloud agents and cheaper
  models need an explicit line between "extend" and "change".

## Consequences
- The compatibility rule is enforced socially (PR template, review) and mechanically (the
  existing test suite must not be edited to accommodate a change).
- `CapabilitySpec.version` remains the mechanism for incompatible capability changes.
- `.ai/ARCHITECTURE.md` and `.ai/MASTER_WORKFLOW.md` §20 ("architecture freeze") are read
  as: the *architecture* is baselined and deviations need an ADR; *contracts* evolve under
  this policy.
