# DE-ADR-021 — Parallel development lanes and unlock milestones

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001

## Context
DE-ADR-006 caps parallel agents at 2 (3 when clearly independent). The architecture must
say *when* that is safe for product work and *what* may never overlap.

## Decision
Waves defined in `docs/IMPLEMENTATION_PLAN.md` §4. Two agents become safe after DE 002 and
DE 003 merge (skeleton, contracts, fakes, CI, import-linter). Three agents become safe after
Wave 2 merges (connector protocol proven by Snowflake + dbt, phase templates stable).
High-conflict areas (`orchestration/`, `domain/`, `capabilities/`, `tools/`, `policy/`,
`approvals/`, `secrets/`, migrations, CI, architecture docs) always have one writer.
Integration order within a wave is recorded in `.ai/TASKS.md`; later lanes refresh from
`main` before PR; a `.ai/local/WORKSTREAMS.md` manifest is created before any multi-agent wave.

## Alternatives
- Parallel from DE 002: rejected — conventions not yet established; conflicts guaranteed.
- No parallelism: rejected — MVP timeline.

## Consequences
- The first two tasks are deliberately sequential and foundational.
- Security lane (DE 011) runs concurrently with feature lanes but owns its directories exclusively.
