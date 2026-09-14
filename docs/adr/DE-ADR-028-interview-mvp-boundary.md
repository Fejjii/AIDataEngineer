# DE-ADR-028 — Constrain the active roadmap to one Interview MVP closed loop

- **Date:** 2026-09-14
- **Status:** PROPOSED
- **Task:** PIVOT001

## Context

PIVOT000 established that the Data Pilot AI control-plane pivot is feasible on the current
foundation, but the accepted DE001 recruiter-ready V1 and DE002–DE019 roadmap are too broad
for the first interview proof. They combine multiple repair classes, GitHub delivery,
staging approval, monitoring, observability, evaluation scenarios, and a frontend before
one complete governed evidence loop has been demonstrated.

PIVOT001 defines the smallest safe contract that can prove the product thesis without
changing accepted operation identity, deterministic policy, approval, provenance,
recovery, connector, or modular-monolith semantics.

## Decision

The active implementation roadmap is:

```text
MVP001 Digital Twin
→ MVP002 Supervisor and Tool Gateway flow
→ MVP003 Repair and Verifier
→ MVP004 End-to-end benchmark and demo hardening
```

The Interview MVP contains one Vantara customer-revenue request, PostgreSQL state, real
Snowflake and dbt Core foundations, one pinned minimal Digital Twin, one deterministic
Supervisor workflow, one governed connector gateway, one injected schema drift, one
allow-listed column-reference repair, one read-only deterministic verifier, and one final
evidence report.

The following accepted architecture choices remain unchanged:

- modular monolith and PostgreSQL state;
- deterministic orchestration with typed, tool-less reasoning capabilities;
- versioned capability and connector contracts;
- server-authorized grants, deterministic policy, and typed approvals;
- immutable operation identity, fenced attempts, and reconcile-before-retry;
- REAL/MOCK provenance and deterministic evaluation.

The previous DE002–DE008A work remains completed historical foundation. The unstarted
DE009–DE019 roadmap is no longer active and is deferred for re-cutting after MVP004
evidence. No task is deleted or represented as completed.

Full contracts, limits, acceptance tests, dependencies, ownership, and effort are in
`docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md`.

## Alternatives

- Continue the DE009–DE019 roadmap unchanged: rejected because it delays proof of the
  closed loop and introduces unrelated product surfaces.
- Implement the broader PIVOT000 revised MVP first: rejected because the second failure,
  GitHub, monitoring, UI, and live LLM are not needed to test the core thesis.
- Redesign the platform around agents, a graph database, or another workflow engine:
  rejected because the current deterministic foundations already support the bounded
  workflow and provide stronger control.

## Consequences

- Implementation resumes only after this ADR and the PIVOT001 contract are accepted.
- MVP001–MVP004 form a sequential critical path because they own high-conflict contracts.
- The first demonstration is intentionally narrow and cannot claim broad enterprise,
  multi-vendor, production, monitoring, migration, or optimization capability.
- Deferred tasks may be reintroduced only from evidence after MVP004; they are not implicit
  Interview MVP requirements.
- DE-ADR-021 remains historical evidence of the original implementation ordering but is
  superseded as the active roadmap by this ADR.
