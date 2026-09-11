# DE-ADR-022 — In-process worker with PostgreSQL task queue

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1)

## Context
Tasks (LLM calls, dbt runs up to 15 min, Snowflake queries) must run asynchronously,
concurrently, durably, and resume after crashes. Redis/Celery were used previously.

## Decision
Tasks are rows; an asyncio worker loop claims `READY` tasks with `SELECT … FOR UPDATE SKIP
LOCKED`, sets a lease, executes with timeout, writes results. Blocking vendor SDK calls run
in bounded thread pools; dbt runs as subprocesses. The worker runs in the API process by
default (`AIDE_WORKER_INPROCESS=true`) and can run as `aide worker` separately.

Retry safety (DE 001R1): the operation identity (`idempotency_key`) is fixed at task
creation and shared by all attempts; the attempt intent row is committed before the handler
runs and the identity is propagated into the external system. On lease expiry the worker
**reconciles before re-executing** (`docs/STATE_MODEL.md` §4.6): a found effect is adopted,
a proven-absent effect is retried with the same key, and an unknown outcome of a
non-idempotent capability (`deploy`) parks the task for a human — it is never repeated
automatically. Immutable artifacts complete the picture.

## Alternatives
- Celery/RQ/arq + Redis: rejected — an extra broker for ≤ 5 workflows; at-least-once
  semantics still require the same idempotency work.
- Temporal: deferred (see DE-ADR-009).

## Consequences
- Throughput limit is low (fine for V1); documented trigger to change.
- Every side-effecting connector handler owes a `reconcile` implementation; the contract
  test kit enforces it.
- Polling interval vs. latency trade-off; `LISTEN/NOTIFY` may be added later without changing contracts.
