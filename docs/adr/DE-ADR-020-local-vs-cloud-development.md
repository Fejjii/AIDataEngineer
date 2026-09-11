# DE-ADR-020 — Local vs Cloud development boundaries for product work

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R2B; OPS004)

## Context
`.ai/ENVIRONMENTS.md` defines LOCAL vs CURSOR_CLOUD generally. Product tasks need a
concrete rule because some require credentials (Snowflake, dbt live, GitHub token) and
some only fakes.

## Decision
A product task is Cloud-eligible iff: it needs only tracked state; fakes and recorded LLM
fixtures suffice for its tests; it needs no credentials; it declares expected files; it
runs on an isolated branch. Tasks that validate against real Snowflake/dbt/GitHub or enter
secrets are LOCAL.

**DE 002 split (mandatory for Cloud launch of the kernel):**

| Task | Environment | Why |
|---|---|---|
| **DE 002A** | **CLOUD** | Pure domain/capability/policy/SQL/import contracts and minimal ruff/mypy/unit/property/import-linter CI. No credentials, no local persistence, no live connectors. |
| **DE 002B** | **CLOUD** | PostgreSQL persistence, fencing, recovery, cancellation and concurrency tests. Requires localhost PostgreSQL 16 in the saved Cursor Cloud environment (OPS003); no vendor credentials. |
| **DE 002C** | **CLOUD** | First executable offline slice composing persistence with fake connectors and replay LLM. Same Cloud environment as DE 002B; no live connectors or secrets. |

Other LOCAL tasks remain: DE 005, 008, 012-live, 017, 018, 019. Live LLM calls in Cloud
only with an explicitly granted key; otherwise fixtures. The architecture is fully
expressed in tracked `docs/` so Cloud agents never need `.ai/private/`.

## Alternatives
- Everything LOCAL: rejected — no parallelism, Mac-bound.
- Everything Cloud with shared credentials: rejected — secret exposure, cannot verify live behaviour safely.
- Treat "DE 002" as a single LOCAL umbrella: rejected in DE 001R2B — contradicts the
  DE 002A/B/C split in `docs/IMPLEMENTATION_PLAN.md` and would block a Cloud DE 002A run.

## Consequences
- Fakes are built early (DE 002A contracts + DE 004 fixtures) to unlock Cloud lanes.
- Each task in `docs/IMPLEMENTATION_PLAN.md` §3 declares Env and Cloud eligibility.
- A Cloud agent must treat DE 002A, DE 002B, and DE 002C as Cloud-eligible. Launching
  DE 002A in Cloud before the DE 001R2B amendment was a governance contradiction; launching
  DE 002B or DE 002C in Cloud before OPS004 was likewise blocked until OPS003 validated
  the saved environment.

## Amendment — OPS004 (2026-09-11)

OPS002 assessed remote development readiness. OPS003 implemented and validated the Cursor
Cloud environment (Python 3.12, uv, PostgreSQL 16 on localhost only, no vendor secrets,
existing DE 002A checks). The operator saved the environment. A fresh Cloud Agent
verification passed.

**Reclassification:** DE 002B and DE 002C are therefore reclassified from LOCAL to CLOUD in
`.ai/TASKS.md` and the table above.

**Credential boundaries unchanged:** This amendment does not relax credential boundaries.
Real Snowflake, live dbt on Snowflake, live staging, production deploy, and secret entry
remain subject to their existing LOCAL or Hybrid restrictions (DE 005, DE 008, DE 012-live,
DE 017, DE 018, DE 019, and related human gates).
