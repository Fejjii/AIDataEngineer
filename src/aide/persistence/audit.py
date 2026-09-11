"""Transactional, monotonic audit event allocation."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from aide.persistence.models import AuditEventModel, AuditSequenceModel

SYSTEM_ACTOR: dict[str, str] = {"kind": "SYSTEM"}


async def append_audit_event(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    event_type: str,
    payload: dict[str, Any],
    actor: dict[str, Any] | None = None,
    phase_run_id: UUID | None = None,
    task_id: UUID | None = None,
    attempt_id: UUID | None = None,
    operation_idempotency_key: str | None = None,
) -> AuditEventModel:
    """Append an audit event inside the caller's business transaction."""
    await session.execute(
        insert(AuditSequenceModel)
        .values(workflow_id=workflow_id, next_sequence=1)
        .on_conflict_do_nothing(index_elements=[AuditSequenceModel.workflow_id])
    )
    sequence_row = await session.scalar(
        select(AuditSequenceModel)
        .where(AuditSequenceModel.workflow_id == workflow_id)
        .with_for_update()
    )
    if sequence_row is None:
        raise RuntimeError("audit sequence allocation failed")
    sequence = sequence_row.next_sequence
    sequence_row.next_sequence += 1
    event = AuditEventModel(
        workflow_id=workflow_id,
        sequence=sequence,
        event_type=event_type,
        phase_run_id=phase_run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        operation_idempotency_key=operation_idempotency_key,
        actor=actor or SYSTEM_ACTOR,
        payload=payload,
    )
    session.add(event)
    await session.flush()
    return event
