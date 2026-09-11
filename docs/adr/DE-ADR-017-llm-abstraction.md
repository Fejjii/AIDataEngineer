# DE-ADR-017 — Thin LLM gateway, structured outputs, versioned prompts

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R2A)

## Context
Provider independence, inspectable prompts, validated outputs, cost accounting, offline
replay, and a redaction boundary are required. LangChain was used previously and must be
re-evaluated.

## Decision
Own `LLMProvider` protocol with adapters on official provider SDKs; requests carry template
id + version, variables, Pydantic output schema, and model config; structured output via
provider JSON-schema/tool mode with fallback extraction + one repair retry; prompts are
versioned files rendered with sandboxed Jinja2; every call is redacted on input, accounted
(tokens, cost from a versioned price table), and recorded as redacted artifacts; a
`FakeProvider` replays recorded fixtures by request fingerprint. Model, temperature, max
tokens and timeout are configurable per capability.

Before provider dispatch, the gateway atomically reserves deterministic worst-case cost
against a locked versioned workflow ledger and settles actual usage afterward. Exceeding
the cap dispatches nothing and requires a `BudgetIncreaseApproval` with explicit new cap
and delta. LLM provider adapters are one of only two adapter classes allowed to resolve
secrets and receive a non-enumerable resolver scoped to their configured `SecretRef`s;
connector adapters receive separate scopes.

## Alternatives
- LangChain/LlamaIndex abstractions: rejected — unneeded layers, version churn.
- LiteLLM proxy: deferred — adopt as an adapter if more than two providers are needed.
- Instructor: not needed; Pydantic + provider schema modes suffice.

## Consequences
- One adapter per provider (~200 LOC); no framework lock-in.
- Prompt changes are diffs in PRs; evaluation records template versions.
