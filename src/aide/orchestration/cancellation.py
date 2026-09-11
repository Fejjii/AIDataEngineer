"""Cancellation intent, fenced ownership, and explicit unresolved-effect parking."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.states import TaskState, WorkflowState
from aide.orchestration.materialization import ConcurrentStateError, acquire_workflow_lock
from aide.orchestration.worker import RecoveryClaim, acquire_recovery
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    TaskAttemptModel,
    UnresolvedEffectModel,
    WorkflowModel,
)


@dataclass(frozen=True)
class CancellationOwnership:
    workflow_id: UUID
    cancellation_epoch: int
    recovery_claims: tuple[RecoveryClaim, ...]


async def request_cancellation(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    expected_workflow_version: int,
    actor_principal_id: UUID,
    reason: str,
    now: datetime,
) -> int:
    """Persist cancellation intent and fencing under workflow serialization."""
    await acquire_workflow_lock(session, workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("workflow does not exist")
    if workflow.version != expected_workflow_version:
        raise ConcurrentStateError("workflow version changed")
    if workflow.state in {
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
        WorkflowState.CANCELLED.value,
    }:
        raise ValueError("terminal workflows cannot be cancelled")
    workflow.state = WorkflowState.CANCEL_REQUESTED.value
    workflow.cancellation_epoch += 1
    workflow.cancellation_requested_by = actor_principal_id
    workflow.cancellation_reason = reason
    workflow.cancellation_requested_at = now
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        event_type="CANCELLATION_REQUESTED",
        actor={"kind": "PRINCIPAL", "principal_id": str(actor_principal_id)},
        payload={"reason": reason, "cancellation_epoch": workflow.cancellation_epoch},
    )
    await session.flush()
    return workflow.cancellation_epoch


async def begin_cancellation(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    expected_workflow_version: int,
    owner: str,
    now: datetime,
    recovery_lease_duration: timedelta,
    reconcile_deadline: datetime,
) -> CancellationOwnership:
    """Cancel unclaimed work and acquire active-effect ownership in a short transaction."""
    await acquire_workflow_lock(session, workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("workflow does not exist")
    if workflow.version != expected_workflow_version:
        raise ConcurrentStateError("workflow version changed")
    if workflow.state != WorkflowState.CANCEL_REQUESTED.value:
        raise ValueError("cancellation intent is not pending")
    workflow.state = WorkflowState.CANCELLING.value
    workflow.version += 1
    tasks = (
        await session.scalars(
            select(MaterializedTaskModel)
            .where(MaterializedTaskModel.workflow_id == workflow_id)
            .order_by(MaterializedTaskModel.task_id)
            .with_for_update()
        )
    ).all()
    claims: list[RecoveryClaim] = []
    for task in tasks:
        if task.status in {
            TaskState.MATERIALIZED.value,
            TaskState.READY.value,
            TaskState.RETRY_WAIT.value,
            TaskState.AWAITING_APPROVAL.value,
        }:
            task.status = TaskState.CANCELLED.value
            task.finished_at = now
            continue
        if task.status in {TaskState.CLAIMED.value, TaskState.RUNNING.value}:
            claim = await acquire_recovery(
                session,
                task_id=task.task_id,
                recovery_owner=owner,
                now=now,
                lease_duration=recovery_lease_duration,
                reconcile_deadline=reconcile_deadline,
                expected_owner=task.lease_owner,
                expected_epoch=task.claim_epoch,
                expected_attempt_id=task.active_attempt_id,
            )
            if claim is not None:
                claims.append(claim)
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        event_type="CANCELLATION_OWNERSHIP_RECORDED",
        payload={
            "owner": owner,
            "cancellation_epoch": workflow.cancellation_epoch,
            "recovery_task_ids": [str(claim.task_id) for claim in claims],
        },
    )
    await session.flush()
    return CancellationOwnership(
        workflow_id=workflow_id,
        cancellation_epoch=workflow.cancellation_epoch,
        recovery_claims=tuple(claims),
    )


async def run_cancellation_io(
    ownership: CancellationOwnership,
    io: Callable[[RecoveryClaim], Awaitable[Any]],
) -> tuple[Any, ...]:
    """Run slow connector cancel/reconcile calls after the lock transaction commits."""
    return tuple([await io(claim) for claim in ownership.recovery_claims])


async def park_unresolved_and_cancel(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    expected_workflow_version: int,
    principal_id: UUID,
    unresolved: Sequence[tuple[RecoveryClaim, dict[str, Any], dict[str, Any]]],
    required_follow_up: str,
    now: datetime,
) -> None:
    """Explicitly park ambiguous effects before terminal cancellation."""
    await acquire_workflow_lock(session, workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("workflow does not exist")
    if workflow.version != expected_workflow_version:
        raise ConcurrentStateError("workflow version changed")
    if workflow.state != WorkflowState.CANCELLING.value:
        raise ValueError("workflow is not cancelling")
    for claim, recovery_context, evidence in unresolved:
        task = await session.get(MaterializedTaskModel, claim.task_id, with_for_update=True)
        attempt = await session.get(TaskAttemptModel, claim.attempt_id, with_for_update=True)
        if (
            task is None
            or attempt is None
            or task.recovery_owner != claim.owner
            or task.claim_epoch != claim.claim_epoch
        ):
            raise RuntimeError("stale cancellation ownership")
        session.add(
            UnresolvedEffectModel(
                workflow_id=workflow_id,
                task_id=task.task_id,
                attempt_id=attempt.attempt_id,
                operation_idempotency_key=task.operation_idempotency_key,
                recovery_context=recovery_context,
                evidence=evidence,
                required_follow_up=required_follow_up,
                created_by_principal_id=principal_id,
            )
        )
        task.status = TaskState.CANCELLED.value
        task.disposition_reason = "UNRESOLVED_EFFECT_PARKED"
        task.finished_at = now
        task.active_attempt_id = None
        task.recovery_owner = None
        task.recovery_lease_expires_at = None
        attempt.outcome = "CANCELLED"
        attempt.finished_at = now
    workflow.state = WorkflowState.CANCELLED.value
    workflow.finished_at = now
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        event_type="WORKFLOW_CANCELLED_WITH_UNRESOLVED_EFFECTS",
        actor={"kind": "PRINCIPAL", "principal_id": str(principal_id)},
        payload={"unresolved_count": len(unresolved)},
    )
    await session.flush()
