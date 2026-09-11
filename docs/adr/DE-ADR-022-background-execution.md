# DE-ADR-022 — In-process worker with PostgreSQL task queue

- **Date:** 2026-09-11 · **Status:** PROPOSED · **Task:** DE 001 · **Amended:** 2026-09-11 (DE 001R1, DE 001R2A, DE 001R2B)

## Context
Tasks (LLM calls, dbt runs up to 15 min, Snowflake queries) must run asynchronously,
concurrently, durably, and resume after crashes. Redis/Celery were used previously.

## Decision
Tasks are rows; an asyncio worker loop claims `READY` tasks with `SELECT … FOR UPDATE SKIP
LOCKED`, sets a lease, executes with timeout, writes results. Blocking vendor SDK calls run
in bounded thread pools; dbt runs as subprocesses. The worker runs in the API process by
default (`AIDE_WORKER_INPROCESS=true`) and can run as `aide worker` separately.

Operation identity exists only after full input materialization/validation and is shared by
all attempts. Claim increments a monotonic fencing epoch; workers renew heartbeats and may
finalize only under matching owner, epoch, attempt and workflow cancellation epoch.
Recovery ownership is acquired atomically by advancing the epoch, so late expired workers
cannot overwrite replacement state.

Retry safety is evidence-based on every failure path. Definite pre-dispatch or authoritative
no-effect rejection may retry within `max_attempts`. Timeout after dispatch, connection or
response loss, fail-after-effect, crash and lease expiry are ambiguous for side effects and
must reconcile first. `EffectFound` requires schema-valid output; `NoEffect` permits a new
attempt only while `attempt_count < max_attempts`, otherwise the task fails; `InProgress`
renews bounded recovery; `Unknown` or exhausted `InProgress` parks.
No ambiguous side effect is blindly repeated.

Cancellation persists intent, stops claims, and advances fencing under a short
serialization lock used only for deterministic coordination and ownership changes.
Cooperative cancel and reconciliation I/O run outside that lock under fenced recovery
ownership. Terminal cancellation requires quiescence or explicit durable parking of
unresolved effects. A human cannot mark success without verified or imported schema-valid
output.

## Alternatives
- Celery/RQ/arq + Redis: rejected — an extra broker for ≤ 5 workflows; at-least-once
  semantics still require the same idempotency work.
- Temporal: deferred (see DE-ADR-009).

## Consequences
- Throughput limit is low (fine for V1); documented trigger to change.
- Every side-effecting connector handler owes a `reconcile` implementation; the contract
  test kit enforces it.
- Polling interval vs. latency trade-off; `LISTEN/NOTIFY` may be added later without changing contracts.
