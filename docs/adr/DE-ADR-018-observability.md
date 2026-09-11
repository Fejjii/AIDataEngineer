# DE-ADR-018 — Observability: audit, telemetry tables, OpenTelemetry, structlog

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001

## Context
Every workflow, task, model call, tool call, approval and cost must be traceable for the
UI timeline, evaluation, and enterprise credibility — without requiring external SaaS.

## Decision
Three streams with shared correlation ids: append-only `audit_events` for consequential
actions; telemetry tables (`model_calls`, `tool_calls`, `workflow_metrics`) for accounting;
`structlog` JSON logs with a redaction processor. OpenTelemetry spans instrument phases,
tasks, policy, model and connector calls with an optional OTLP exporter. Provider-reported
token usage and a versioned price table give reproducible cost. Prompts/completions are
stored as redacted artifacts with retention.

## Alternatives
- Langfuse/LangSmith as the primary store: rejected for V1 — external dependency for core
  product data; may be added as an exporter.
- Logs only: rejected — the UI and evaluation need structured queryable rows.

## Consequences
- Telemetry writes are part of the Tool Registry and LLM Gateway, so they cannot be
  forgotten by feature code.
- PostgreSQL holds telemetry; retention jobs are operator commands.
