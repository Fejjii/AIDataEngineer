# DE-ADR-021 — Parallel development lanes and unlock milestones

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R2A, DE 001R2B; OPS004)

## Context
DE-ADR-006 caps parallel agents at 2 (3 when clearly independent). The architecture must
say *when* that is safe for product work and *what* may never overlap.

## Decision
Wave 0 is sequential: DE 002A contract kernel + minimal CI (**CLOUD**) → DE 002B durable
phase-run/fencing/recovery kernel (**CLOUD**) → DE 002C offline safe-SQL slice (**CLOUD**)
→ DE 003 Docker and CI expansion (**CLOUD**). Two agents become safe only after all four
merge. Three agents become safe after Wave 2 merges (connector protocol proven by Snowflake
+ dbt, phase templates stable).
High-conflict areas (`orchestration/`, `domain/`, `capabilities/`, `tools/`, `policy/`,
`approvals/`, `secrets/`, migrations, CI, architecture docs) always have one writer.
Integration order within a wave is recorded in `.ai/TASKS.md`; later lanes refresh from
`main` before PR; a `.ai/local/WORKSTREAMS.md` manifest is created before any multi-agent wave.

## Alternatives
- Parallel from DE 002: rejected — conventions not yet established; conflicts guaranteed.
- No parallelism: rejected — MVP timeline.

## Consequences
- The complete foundational sequence is single-writer; CI protects pure contracts before
  persistence or slice implementation begins.
- Security lane (DE 011) runs concurrently with feature lanes but owns its directories exclusively.
