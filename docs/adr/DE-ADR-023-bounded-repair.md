# DE-ADR-023 — Bounded self-repair loop

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001

## Context
Self-correction is a core differentiator and the largest source of runaway cost and unsafe
behaviour if unbounded.

## Decision
Repair is a deterministic loop owned by the orchestrator (`docs/PERMISSION_MODEL.md` §11):
only failure classes in the repairable set enter it; each cycle requires an evidence bundle,
an LLM `RepairProposal` with a **novel hypothesis hash**, deterministic validation (class,
scope, SQL safety, compile/EXPLAIN, tests-not-weakened), and re-validation that the failed
check passes with no regression. Budgets: 2 per task, 4 per workflow, 2 rejected proposals
per failure; termination escalates to `BLOCKED` with full evidence. Repair never invokes
repair; `UNKNOWN` and non-repairable classes never enter.

## Alternatives
- "Retry until green" agent loop: rejected — unbounded, may weaken tests.
- No auto-repair: rejected — removes the key value proposition.

## Consequences
- Some fixable failures stop early and need a human; acceptable and visible.
- Repair history becomes demo content (distinct hypotheses, evidence).
