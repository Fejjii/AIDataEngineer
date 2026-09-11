# DE-ADR-020 — Local vs Cloud development boundaries for product work

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001

## Context
`.ai/ENVIRONMENTS.md` defines LOCAL vs CURSOR_CLOUD generally. Product tasks need a
concrete rule because some require credentials (Snowflake, dbt live, GitHub token) and
some only fakes.

## Decision
A product task is Cloud-eligible iff: it needs only tracked state; fakes and recorded LLM
fixtures suffice for its tests; it needs no credentials; it declares expected files; it
runs on an isolated branch. Tasks that validate against real Snowflake/dbt/GitHub or enter
secrets are LOCAL (DE 002, 005, 008, 012-live, 017, 018, 019). Live LLM calls in Cloud only
with an explicitly granted key; otherwise fixtures. The architecture is fully expressed in
tracked `docs/` so Cloud agents never need `.ai/private/`.

## Alternatives
- Everything LOCAL: rejected — no parallelism, Mac-bound.
- Everything Cloud with shared credentials: rejected — secret exposure, cannot verify live behaviour safely.

## Consequences
- Fakes are built early (DE 002/DE 004) to unlock Cloud lanes.
- Each task in `docs/IMPLEMENTATION_PLAN.md` §3 declares Env and Cloud eligibility.
