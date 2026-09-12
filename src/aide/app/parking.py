"""Application-layer parking and fail-closed policy dispositions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.states import AttemptOutcome, TaskState, WorkflowState
from aide.orchestration.materialization import acquire_workflow_lock
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskAttemptModel,
    WorkflowModel,
)


async def park_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    reason: str,
    now: datetime,
    routing: str = "PARK",
    reasons: tuple[str, ...] = (),
) -> None:
    """ENVIRONMENTAL policy denials park the task and block the workflow."""
    task = await session.get(MaterializedTaskModel, task_id, with_for_update=True)
    if task is None:
        raise LookupError("task does not exist")
    await acquire_workflow_lock(session, task.workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == task.workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("workflow does not exist")
    phase_run = await session.get(PhaseRunModel, task.phase_run_id)
    task.status = TaskState.PARKED.value
    task.failure_classification = "POLICY_DENIED"
    task.disposition_reason = reason
    task.finished_at = now
    attempt_id = task.active_attempt_id
    task.lease_owner = None
    task.lease_expires_at = None
    task.active_attempt_id = None
    task.recovery_owner = None
    task.recovery_lease_expires_at = None
    if attempt_id is not None:
        attempt = await session.get(TaskAttemptModel, attempt_id, with_for_update=True)
        if attempt is not None:
            attempt.outcome = AttemptOutcome.FAILED.value
            attempt.failure_classification = "POLICY_DENIED"
            attempt.finished_at = now
    workflow.state = WorkflowState.BLOCKED.value
    workflow.blocked_from_phase = phase_run.phase if phase_run is not None else workflow.state
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="TASK_PARKED",
        payload={"reason": reason, "routing": routing, "reasons": list(reasons)},
    )
    await session.flush()


async def fail_closed_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    reason: str,
    now: datetime,
    routing: str = "FAIL_CLOSED",
    reasons: tuple[str, ...] = (),
) -> None:
    """SCOPE/SECURITY denials fail the task and workflow with durable audit."""
    task = await session.get(MaterializedTaskModel, task_id, with_for_update=True)
    if task is None:
        raise LookupError("task does not exist")
    await acquire_workflow_lock(session, task.workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == task.workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("workflow does not exist")
    attempt_id = task.active_attempt_id
    task.status = TaskState.FAILED.value
    task.failure_classification = "POLICY_DENIED"
    task.disposition_reason = reason
    task.finished_at = now
    task.lease_owner = None
    task.lease_expires_at = None
    task.active_attempt_id = None
    task.recovery_owner = None
    task.recovery_lease_expires_at = None
    if attempt_id is not None:
        attempt = await session.get(TaskAttemptModel, attempt_id, with_for_update=True)
        if attempt is not None:
            attempt.outcome = AttemptOutcome.FAILED.value
            attempt.failure_classification = "POLICY_DENIED"
            attempt.finished_at = now
    workflow.state = WorkflowState.FAILED.value
    workflow.finished_at = now
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="POLICY_DENIED",
        payload={"reason": reason, "routing": routing, "reasons": list(reasons)},
    )
    await session.flush()
