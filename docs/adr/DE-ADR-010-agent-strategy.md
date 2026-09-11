# DE-ADR-010 — Single orchestrator with reasoning capabilities; no specialist agents

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001

## Context
The vision brief lists ten candidate agents. The task brief asks to avoid theatrical
multi-agent architecture and justify every specialist.

## Decision
One deterministic orchestrator; one planning capability; eight **reasoning capabilities**
(`docs/AGENT_MODEL.md` §3) with role prompts, bounded context, typed outputs and
deterministic validators. Reasoning capabilities have no tools, no loops, no state access
beyond what the orchestrator hands them, and `READ` permission only. Zero specialist agents
in V1. A specialist may be added later only as a sub-workflow meeting the four criteria in
`docs/AGENT_MODEL.md` §5.

## Alternatives
- **Orchestrator + specialist agents with own tools** (Discovery, SQL, Quality, …):
  rejected — duplicated policy surfaces, unbounded loops, text as integration medium,
  unauditable.
- **Single monolithic prompt "do everything"**: rejected — no typed intermediate state, no
  validation points.

## Consequences
- Specialisation lives in prompts and context assemblers, which are versioned files.
- Every LLM output is a proposal validated by code before effect.
- The demo's credibility comes from the audit timeline rather than agent chatter.
