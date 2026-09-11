"""PostgreSQL task claiming, heartbeats, fencing, and recovery ownership."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.identity import canonical_json_bytes
from aide.domain.states import AttemptOutcome, DispatchState, TaskState, WorkflowState
from aide.persistence.audit import append_audit_event
from aide.persistence.models import MaterializedTaskModel, TaskAttemptModel, WorkflowModel


@dataclass(frozen=True)
class TaskClaim:
    task_id: UUID
    attempt_id: UUID
    owner: str
    claim_epoch: int
    cancellation_epoch: int
    attempt_number: int
    lease_expires_at: datetime


@dataclass(frozen=True)
class RecoveryClaim:
    task_id: UUID
    attempt_id: UUID
    owner: str
    claim_epoch: int
    lease_expires_at: datetime


async def claim_task(
    session: AsyncSession,
    *,
    owner: str,
    now: datetime,
    lease_duration: timedelta,
) -> TaskClaim | None:
    """Claim one runnable task with SKIP LOCKED and create exactly one attempt."""
    task = await session.scalar(
        select(MaterializedTaskModel)
        .join(WorkflowModel, WorkflowModel.workflow_id == MaterializedTaskModel.workflow_id)
        .where(
            MaterializedTaskModel.status.in_([TaskState.READY.value, TaskState.RETRY_WAIT.value]),
            or_(
                MaterializedTaskModel.retry_not_before.is_(None),
                MaterializedTaskModel.retry_not_before <= now,
            ),
            WorkflowModel.state.notin_(
                [
                    WorkflowState.CANCEL_REQUESTED.value,
                    WorkflowState.CANCELLING.value,
                    WorkflowState.CANCELLED.value,
                ]
            ),
            MaterializedTaskModel.attempt_count < MaterializedTaskModel.max_attempts,
        )
        .order_by(MaterializedTaskModel.created_at, MaterializedTaskModel.task_id)
        .with_for_update(skip_locked=True, of=MaterializedTaskModel)
        .limit(1)
    )
    if task is None:
        return None
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == task.workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("claimable task has no workflow")
    task.claim_epoch += 1
    task.attempt_count += 1
    attempt_id = uuid4()
    lease_expires_at = now + lease_duration
    task.status = TaskState.CLAIMED.value
    task.lease_owner = owner
    task.lease_expires_at = lease_expires_at
    task.last_heartbeat_at = now
    task.claimed_at = now
    task.active_attempt_id = attempt_id
    task.retry_not_before = None
    attempt = TaskAttemptModel(
        attempt_id=attempt_id,
        task_id=task.task_id,
        phase_run_id=task.phase_run_id,
        attempt_number=task.attempt_count,
        operation_idempotency_key=task.operation_idempotency_key,
        resolved_input_digest=task.resolved_input_digest,
        lease_owner=owner,
        claim_epoch=task.claim_epoch,
        cancellation_epoch=workflow.cancellation_epoch,
        started_at=now,
        last_heartbeat_at=now,
        dispatch_state=DispatchState.NOT_DISPATCHED.value,
        outcome=AttemptOutcome.STARTED.value,
    )
    session.add(attempt)
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="TASK_CLAIMED",
        payload={
            "owner": owner,
            "claim_epoch": task.claim_epoch,
            "attempt_number": task.attempt_count,
        },
    )
    await session.flush()
    return TaskClaim(
        task_id=task.task_id,
        attempt_id=attempt_id,
        owner=owner,
        claim_epoch=task.claim_epoch,
        cancellation_epoch=workflow.cancellation_epoch,
        attempt_number=task.attempt_count,
        lease_expires_at=lease_expires_at,
    )


async def mark_dispatched(session: AsyncSession, claim: TaskClaim) -> bool:
    locked = await _owned_task(session, claim)
    if locked is None:
        return False
    task, attempt, _ = locked
    task.status = TaskState.RUNNING.value
    attempt.dispatch_state = DispatchState.DISPATCHED.value
    await session.flush()
    return True


async def renew_heartbeat(
    session: AsyncSession,
    *,
    claim: TaskClaim,
    now: datetime,
    lease_duration: timedelta,
) -> bool:
    locked = await _owned_task(session, claim)
    if locked is None:
        return False
    task, attempt, _ = locked
    if task.status not in {TaskState.CLAIMED.value, TaskState.RUNNING.value}:
        return False
    task.last_heartbeat_at = now
    task.lease_expires_at = now + lease_duration
    attempt.last_heartbeat_at = now
    await session.flush()
    return True


async def finalize_success(
    session: AsyncSession,
    *,
    claim: TaskClaim,
    output: dict[str, Any],
    now: datetime,
    recovered: bool = False,
) -> bool:
    """Adopt output only when owner, epoch, attempt, and cancellation epoch still match."""
    locked = await _owned_task(session, claim)
    if locked is None:
        return False
    task, attempt, _ = locked
    if task.outputs is not None:
        return False
    digest = hashlib.sha256(canonical_json_bytes(output)).hexdigest()
    task.outputs = output
    task.output_digest = digest
    task.execution_result = {"recovered": recovered}
    task.status = TaskState.SUCCEEDED.value
    task.finished_at = now
    task.lease_owner = None
    task.lease_expires_at = None
    task.active_attempt_id = None
    task.recovery_owner = None
    task.recovery_lease_expires_at = None
    attempt.result = output
    attempt.output_digest = digest
    attempt.outcome = (
        AttemptOutcome.RECOVERED.value if recovered else AttemptOutcome.SUCCEEDED.value
    )
    attempt.finished_at = now
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=claim.attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="TASK_RECOVERED" if recovered else "TASK_SUCCEEDED",
        payload={"claim_epoch": claim.claim_epoch, "output_digest": digest},
    )
    await session.flush()
    return True


async def finalize_failure(
    session: AsyncSession,
    *,
    claim: TaskClaim,
    failure_classification: str,
    now: datetime,
) -> bool:
    locked = await _owned_task(session, claim)
    if locked is None:
        return False
    task, attempt, _ = locked
    task.status = TaskState.FAILED.value
    task.failure_classification = failure_classification
    task.finished_at = now
    task.lease_owner = None
    task.lease_expires_at = None
    task.active_attempt_id = None
    attempt.failure_classification = failure_classification
    attempt.outcome = AttemptOutcome.FAILED.value
    attempt.finished_at = now
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=claim.attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="TASK_FAILED",
        payload={"failure_classification": failure_classification},
    )
    await session.flush()
    return True


async def acquire_recovery(
    session: AsyncSession,
    *,
    task_id: UUID,
    recovery_owner: str,
    now: datetime,
    lease_duration: timedelta,
    reconcile_deadline: datetime,
    expected_owner: str | None = None,
    expected_epoch: int | None = None,
    expected_attempt_id: UUID | None = None,
) -> RecoveryClaim | None:
    """Atomically fence a prior worker and claim reconciliation ownership."""
    task = await session.scalar(
        select(MaterializedTaskModel)
        .where(MaterializedTaskModel.task_id == task_id)
        .with_for_update(skip_locked=True)
    )
    if task is None or task.active_attempt_id is None:
        return None
    if expected_owner is not None and task.lease_owner != expected_owner:
        return None
    if expected_epoch is not None and task.claim_epoch != expected_epoch:
        return None
    if expected_attempt_id is not None and task.active_attempt_id != expected_attempt_id:
        return None
    attempt = await session.get(TaskAttemptModel, task.active_attempt_id, with_for_update=True)
    if attempt is None:
        raise LookupError("active attempt does not exist")
    prior_attempt_id = task.active_attempt_id
    task.claim_epoch += 1
    task.status = TaskState.RECONCILING.value
    task.recovery_owner = recovery_owner
    task.recovery_lease_expires_at = now + lease_duration
    task.reconcile_deadline = reconcile_deadline
    task.reconcile_check_count = 0
    task.lease_owner = None
    task.lease_expires_at = None
    attempt.dispatch_state = DispatchState.OUTCOME_AMBIGUOUS.value
    attempt.outcome = AttemptOutcome.AMBIGUOUS.value
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=prior_attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="RECOVERY_CLAIMED",
        payload={"recovery_owner": recovery_owner, "claim_epoch": task.claim_epoch},
    )
    await session.flush()
    return RecoveryClaim(
        task_id=task.task_id,
        attempt_id=prior_attempt_id,
        owner=recovery_owner,
        claim_epoch=task.claim_epoch,
        lease_expires_at=now + lease_duration,
    )


async def acquire_expired_recovery(
    session: AsyncSession,
    *,
    recovery_owner: str,
    now: datetime,
    lease_duration: timedelta,
    reconcile_deadline: datetime,
) -> RecoveryClaim | None:
    expired = await session.scalar(
        select(MaterializedTaskModel)
        .where(
            MaterializedTaskModel.status.in_([TaskState.CLAIMED.value, TaskState.RUNNING.value]),
            MaterializedTaskModel.lease_expires_at < now,
        )
        .order_by(MaterializedTaskModel.lease_expires_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if expired is None:
        return None
    return await acquire_recovery(
        session,
        task_id=expired.task_id,
        recovery_owner=recovery_owner,
        now=now,
        lease_duration=lease_duration,
        reconcile_deadline=reconcile_deadline,
        expected_owner=expired.lease_owner,
        expected_epoch=expired.claim_epoch,
        expected_attempt_id=expired.active_attempt_id,
    )


async def _owned_task(
    session: AsyncSession, claim: TaskClaim
) -> tuple[MaterializedTaskModel, TaskAttemptModel, WorkflowModel] | None:
    task = await session.scalar(
        select(MaterializedTaskModel)
        .where(
            MaterializedTaskModel.task_id == claim.task_id,
            MaterializedTaskModel.lease_owner == claim.owner,
            MaterializedTaskModel.claim_epoch == claim.claim_epoch,
            MaterializedTaskModel.active_attempt_id == claim.attempt_id,
        )
        .with_for_update()
    )
    if task is None:
        return None
    workflow = await session.scalar(
        select(WorkflowModel)
        .where(
            WorkflowModel.workflow_id == task.workflow_id,
            WorkflowModel.cancellation_epoch == claim.cancellation_epoch,
        )
        .with_for_update()
    )
    if workflow is None:
        return None
    attempt = await session.scalar(
        select(TaskAttemptModel)
        .where(
            TaskAttemptModel.attempt_id == claim.attempt_id,
            TaskAttemptModel.lease_owner == claim.owner,
            TaskAttemptModel.claim_epoch == claim.claim_epoch,
            TaskAttemptModel.cancellation_epoch == claim.cancellation_epoch,
        )
        .with_for_update()
    )
    if attempt is None:
        return None
    return task, attempt, workflow
