"""Cancellation intent, fenced ownership, and explicit unresolved-effect parking."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.states import AttemptOutcome, TaskState, WorkflowState
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


_CANCELLABLE_WITHOUT_EFFECT = {
    TaskState.MATERIALIZED.value,
    TaskState.READY.value,
    TaskState.RETRY_WAIT.value,
    TaskState.AWAITING_APPROVAL.value,
}
_ACTIVE_EFFECT_STATES = {
    TaskState.CLAIMED.value,
    TaskState.RUNNING.value,
    TaskState.RECONCILING.value,
}
_QUIESCENT_TASK_STATES = {
    TaskState.SUCCEEDED.value,
    TaskState.FAILED.value,
    TaskState.SKIPPED.value,
    TaskState.CANCELLED.value,
}


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
        can_cancel_parked = (
            task.status == TaskState.PARKED.value
            and task.failure_classification != "AMBIGUOUS_OUTCOME"
        )
        if task.status in _CANCELLABLE_WITHOUT_EFFECT or can_cancel_parked:
            task.status = TaskState.CANCELLED.value
            task.finished_at = now
            continue
        is_parked_ambiguous = (
            task.status == TaskState.PARKED.value
            and task.failure_classification == "AMBIGUOUS_OUTCOME"
        )
        if task.status in _ACTIVE_EFFECT_STATES or is_parked_ambiguous:
            if is_parked_ambiguous:
                await _restore_ambiguous_attempt_for_cancellation(session, task)
            prior_owner = (
                task.recovery_owner
                if task.status == TaskState.RECONCILING.value
                else task.lease_owner
            )
            claim = await acquire_recovery(
                session,
                task_id=task.task_id,
                recovery_owner=owner,
                now=now,
                lease_duration=recovery_lease_duration,
                reconcile_deadline=reconcile_deadline,
                expected_owner=prior_owner,
                expected_epoch=task.claim_epoch,
                expected_attempt_id=task.active_attempt_id,
                expected_cancellation_epoch=workflow.cancellation_epoch,
                for_cancellation=True,
            )
            if claim is None:
                raise RuntimeError("failed to acquire cancellation recovery ownership")
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


async def _restore_ambiguous_attempt_for_cancellation(
    session: AsyncSession,
    task: MaterializedTaskModel,
) -> None:
    """Reattach a parked effect's historical attempt for fenced reconciliation."""
    if (
        task.active_attempt_id is not None
        or task.lease_owner is not None
        or task.recovery_owner is not None
    ):
        raise RuntimeError("parked ambiguous task unexpectedly retains ownership")
    attempt = await session.scalar(
        select(TaskAttemptModel)
        .where(
            TaskAttemptModel.task_id == task.task_id,
            TaskAttemptModel.outcome == AttemptOutcome.AMBIGUOUS.value,
        )
        .order_by(TaskAttemptModel.attempt_number.desc())
        .with_for_update()
        .limit(1)
    )
    if (
        attempt is None
        or attempt.operation_idempotency_key != task.operation_idempotency_key
        or attempt.resolved_input_digest != task.resolved_input_digest
    ):
        raise RuntimeError("parked ambiguous task has no matching historical attempt")
    task.status = TaskState.RECONCILING.value
    task.active_attempt_id = attempt.attempt_id
    task.disposition_reason = None


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
    tasks = (
        await session.scalars(
            select(MaterializedTaskModel)
            .where(MaterializedTaskModel.workflow_id == workflow_id)
            .order_by(MaterializedTaskModel.task_id)
            .with_for_update()
        )
    ).all()
    unresolved_by_task = {item[0].task_id: item for item in unresolved}
    if len(unresolved_by_task) != len(unresolved):
        raise ValueError("unresolved effects must name each task exactly once")
    active_task_ids = {task.task_id for task in tasks if task.status in _ACTIVE_EFFECT_STATES}
    if set(unresolved_by_task) != active_task_ids:
        raise ValueError("unresolved effects must exactly cover every active task")

    tasks_by_id = {task.task_id: task for task in tasks}
    for claim, recovery_context, evidence in unresolved:
        task = tasks_by_id[claim.task_id]
        attempt = await session.get(TaskAttemptModel, claim.attempt_id, with_for_update=True)
        if (
            attempt is None
            or task.workflow_id != workflow_id
            or task.status != TaskState.RECONCILING.value
            or task.recovery_owner != claim.owner
            or task.claim_epoch != claim.claim_epoch
            or task.active_attempt_id != claim.attempt_id
            or claim.cancellation_epoch != workflow.cancellation_epoch
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
        task.lease_owner = None
        task.lease_expires_at = None
        task.recovery_owner = None
        task.recovery_lease_expires_at = None
        attempt.outcome = AttemptOutcome.CANCELLED.value
        attempt.finished_at = now
    await session.flush()
    _assert_terminal_task_quiescence(tasks)
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


async def complete_cancellation(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    expected_workflow_version: int,
    now: datetime,
) -> None:
    """Terminalize cancellation only after every task is durably quiescent."""
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
    tasks = (
        await session.scalars(
            select(MaterializedTaskModel)
            .where(MaterializedTaskModel.workflow_id == workflow_id)
            .order_by(MaterializedTaskModel.task_id)
            .with_for_update()
        )
    ).all()
    _assert_terminal_task_quiescence(tasks)
    unresolved_effect = await session.scalar(
        select(UnresolvedEffectModel.unresolved_effect_id)
        .where(UnresolvedEffectModel.workflow_id == workflow_id)
        .limit(1)
    )
    if unresolved_effect is not None:
        raise ValueError("normal cancellation cannot hide a durable unresolved effect")
    workflow.state = WorkflowState.CANCELLED.value
    workflow.finished_at = now
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        event_type="WORKFLOW_CANCELLED",
        payload={"unresolved_count": 0},
    )
    await session.flush()


def _assert_terminal_task_quiescence(tasks: Sequence[MaterializedTaskModel]) -> None:
    for task in tasks:
        if task.status not in _QUIESCENT_TASK_STATES:
            raise ValueError(f"task {task.task_id} is not quiescent")
        if (
            task.lease_owner is not None
            or task.lease_expires_at is not None
            or task.recovery_owner is not None
            or task.recovery_lease_expires_at is not None
            or task.active_attempt_id is not None
        ):
            raise ValueError(f"task {task.task_id} retains active ownership")
