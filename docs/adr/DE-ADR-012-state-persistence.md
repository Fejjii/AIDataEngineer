# DE-ADR-012 — PostgreSQL + SQLAlchemy 2 + Alembic for all state

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001

## Context
Workflow, task, artifact, approval, audit, telemetry and evaluation state must be durable,
queryable, concurrency-safe, and self-hostable offline.

## Decision
PostgreSQL 16 as the only stateful service. SQLAlchemy 2.0 typed ORM with repository
classes and a unit-of-work; Alembic migrations; JSONB for typed payloads (validated by
Pydantic at the boundary); `bytea`/`jsonb` artifact bodies behind a blob-store interface.
PostgreSQL also hosts the synthetic source schemas.

## Alternatives
- SQLite: rejected — no `SKIP LOCKED`, weak concurrency for workers.
- Redis for queue/state: rejected — second stateful service, not durable by default.
- Document store: rejected — transactional guarantees and joins matter for audit.
- Object storage for artifacts now: deferred — interface exists; V1 volumes are small.

## Consequences
- One migration chain — a high-conflict file set with one writer at a time.
- Integration tests need PostgreSQL (compose/testcontainers); unit tests use in-memory fakes.
