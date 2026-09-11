# DE-ADR-019 — In-repo evaluation harness; no LLM judge for pass/fail

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001

## Context
The product claim is measurable: safely produce, execute, test, repair, deliver, at a
known cost. Claims must come from evidence, deterministic in CI.

## Decision
`aide eval` harness drives scenarios (YAML) through Application Services against fake or
real connectors; scores from persisted artifacts using the metric definitions in
`docs/EVALUATION_STRATEGY.md` §3; offline mode replays recorded LLM fixtures for
determinism and runs in CI as a regression gate; live modes report distributions over N
runs. Time-saved uses a versioned manual baseline and is labelled an estimate. No
LLM-as-judge decides pass/fail.

## Alternatives
- Prompt-evaluation frameworks (promptfoo, DeepEval, Ragas): rejected as primary — they
  score prompts, not multi-step governed workflows; may be used for prompt-level checks.
- LLM judges: rejected for pass/fail — circular and non-deterministic.

## Consequences
- Recorded LLM fixtures must be redacted and reviewed; re-recording is a deliberate task.
- Evaluation shares code paths with the product, so it also serves as integration testing.
