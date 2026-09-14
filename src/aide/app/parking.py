"""Application-layer parking and fail-closed policy dispositions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.approvals import ApprovalRecord, ApprovalStatus, ApprovalSubject
from aide.domain.identity import compute_resolved_input_digest
from aide.domain.principal import PrincipalRef
from aide.domain.states import AttemptOutcome, TaskState, WorkflowState
from aide.orchestration.materialization import acquire_workflow_lock
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskAttemptModel,
    WorkflowModel,
)
from aide.persistence.repositories import ApprovalRepository


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


async def await_approval_task(
    session: AsyncSession,
    *,
    task_id: UUID,
    now: datetime,
    principal: PrincipalRef,
    requirements: tuple[ApprovalSubject, ...],
    routing: str = "APPROVAL",
) -> tuple[UUID, ...]:
    """Persist approval requirements and wait without failing the workflow."""
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
    approvals = ApprovalRepository(session)
    existing = await approvals.list_for_workflow(task.workflow_id)
    pending = {
        record.subject_digest: record.approval_id
        for record in existing
        if record.status is ApprovalStatus.PENDING
    }
    approval_ids: list[UUID] = []
    for requirement in requirements:
        digest = compute_resolved_input_digest(requirement)
        existing_id = pending.get(digest)
        if existing_id is not None:
            approval_ids.append(existing_id)
            continue
        record = ApprovalRecord(
            approval_id=uuid4(),
            workflow_id=task.workflow_id,
            subject=requirement,
            subject_digest=digest,
            requester=principal,
            status=ApprovalStatus.PENDING,
            created_at=now,
            expires_at=requirement.expires_at,
        )
        await approvals.add(record, task_id=task.task_id, mandatory=True)
        pending[digest] = record.approval_id
        approval_ids.append(record.approval_id)
    attempt_id = task.active_attempt_id
    task.status = TaskState.AWAITING_APPROVAL.value
    task.failure_classification = None
    task.disposition_reason = "APPROVAL_REQUIRED"
    task.finished_at = None
    task.lease_owner = None
    task.lease_expires_at = None
    task.active_attempt_id = None
    task.recovery_owner = None
    task.recovery_lease_expires_at = None
    if attempt_id is not None:
        attempt = await session.get(TaskAttemptModel, attempt_id, with_for_update=True)
        if attempt is not None:
            attempt.outcome = AttemptOutcome.FAILED.value
            attempt.failure_classification = "APPROVAL_REQUIRED"
            attempt.finished_at = now
    workflow.state = WorkflowState.APPROVAL_REQUIRED.value
    workflow.blocked_from_phase = phase_run.phase if phase_run is not None else workflow.state
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type="APPROVAL_REQUIRED",
        payload={
            "routing": routing,
            "approval_ids": [str(item) for item in approval_ids],
            "requirement_kinds": [requirement.kind for requirement in requirements],
        },
    )
    await session.flush()
    return tuple(approval_ids)


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
