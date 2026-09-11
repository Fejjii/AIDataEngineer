"""Serialized phase reduction, dependency propagation, and advancement."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.states import PhaseRunStatus, TaskState, WorkflowState
from aide.orchestration.materialization import (
    ConcurrentStateError,
    TemplateSpec,
    acquire_workflow_lock,
    create_phase_occurrence,
)
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskTemplateModel,
    TemplateDispositionModel,
    WorkflowModel,
)

ACTIVE_TASK_STATES = {
    TaskState.MATERIALIZED.value,
    TaskState.READY.value,
    TaskState.CLAIMED.value,
    TaskState.RUNNING.value,
    TaskState.AWAITING_APPROVAL.value,
    TaskState.RETRY_WAIT.value,
    TaskState.RECONCILING.value,
}


@dataclass(frozen=True)
class NextPhase:
    phase_run_id: UUID
    phase: WorkflowState
    contract_snapshot_id: UUID
    templates: Sequence[TemplateSpec]
    phase_exit_criteria: Sequence[str] = ()


async def propagate_required_dependency_failures(
    session: AsyncSession, *, phase_run_id: UUID
) -> int:
    """Give every blocked required dependant an explicit deterministic disposition."""
    templates = (
        await session.scalars(
            select(TaskTemplateModel)
            .where(TaskTemplateModel.phase_run_id == phase_run_id)
            .order_by(TaskTemplateModel.local_id)
            .with_for_update()
        )
    ).all()
    tasks = (
        await session.scalars(
            select(MaterializedTaskModel)
            .where(MaterializedTaskModel.phase_run_id == phase_run_id)
            .with_for_update()
        )
    ).all()
    dispositions = (
        await session.scalars(
            select(TemplateDispositionModel).where(
                TemplateDispositionModel.phase_run_id == phase_run_id
            )
        )
    ).all()
    existing = {item.template_id for item in dispositions}
    template_by_id = {item.template_id: item for item in templates}
    outcomes = {task.local_id: task.status for task in tasks}
    outcomes.update(
        {
            template_by_id[item.template_id].local_id: item.status
            for item in dispositions
            if item.template_id in template_by_id
        }
    )
    terminal_failure = {
        TaskState.FAILED.value,
        TaskState.PARKED.value,
        TaskState.CANCELLED.value,
        TaskState.SKIPPED.value,
    }
    created = 0
    for template in templates:
        if template.template_id in existing or template.local_id in outcomes:
            continue
        for dependency_local_id in sorted(template.required_dependencies):
            if outcomes.get(dependency_local_id) not in terminal_failure:
                continue
            session.add(
                TemplateDispositionModel(
                    template_id=template.template_id,
                    phase_run_id=phase_run_id,
                    status=TaskState.SKIPPED.value,
                    reason="UPSTREAM_FAILED",
                    upstream_local_id=dependency_local_id,
                )
            )
            outcomes[template.local_id] = TaskState.SKIPPED.value
            created += 1
            break
    await session.flush()
    return created


async def reduce_and_advance(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    expected_workflow_version: int,
    expected_generation: int,
    next_phase: NextPhase | None,
) -> PhaseRunModel | None:
    """Reduce one phase and create at most one subsequent phase occurrence."""
    await acquire_workflow_lock(session, workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id).with_for_update()
    )
    if workflow is None or workflow.active_phase_run_id is None:
        raise LookupError("workflow has no active phase occurrence")
    if workflow.version != expected_workflow_version:
        raise ConcurrentStateError("workflow version changed")
    phase_run = await session.scalar(
        select(PhaseRunModel)
        .where(PhaseRunModel.phase_run_id == workflow.active_phase_run_id)
        .with_for_update()
    )
    if phase_run is None:
        raise LookupError("active phase occurrence does not exist")
    if phase_run.generation != expected_generation:
        raise ConcurrentStateError("phase generation changed")

    await propagate_required_dependency_failures(session, phase_run_id=phase_run.phase_run_id)
    task_states = list(
        (
            await session.scalars(
                select(MaterializedTaskModel.status).where(
                    MaterializedTaskModel.phase_run_id == phase_run.phase_run_id
                )
            )
        ).all()
    )
    template_count = len(
        (
            await session.scalars(
                select(TaskTemplateModel.template_id).where(
                    TaskTemplateModel.phase_run_id == phase_run.phase_run_id
                )
            )
        ).all()
    )
    disposition_count = len(
        (
            await session.scalars(
                select(TemplateDispositionModel.disposition_id).where(
                    TemplateDispositionModel.phase_run_id == phase_run.phase_run_id
                )
            )
        ).all()
    )
    if any(status in ACTIVE_TASK_STATES for status in task_states):
        return None
    if len(task_states) + disposition_count != template_count:
        return None
    if TaskState.PARKED.value in task_states:
        phase_run.status = PhaseRunStatus.BLOCKED.value
        workflow.blocked_from_phase = phase_run.phase
        workflow.state = WorkflowState.BLOCKED.value
        workflow.version += 1
        await append_audit_event(
            session,
            workflow_id=workflow_id,
            phase_run_id=phase_run.phase_run_id,
            event_type="PHASE_BLOCKED",
            payload={"generation": phase_run.generation},
        )
        return None
    if TaskState.FAILED.value in task_states:
        phase_run.status = PhaseRunStatus.FAILED.value
        workflow.state = WorkflowState.FAILED.value
        workflow.version += 1
        await append_audit_event(
            session,
            workflow_id=workflow_id,
            phase_run_id=phase_run.phase_run_id,
            event_type="PHASE_FAILED",
            payload={"generation": phase_run.generation},
        )
        return None

    phase_run.status = PhaseRunStatus.SUCCEEDED.value
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        phase_run_id=phase_run.phase_run_id,
        event_type="PHASE_SUCCEEDED",
        payload={"generation": phase_run.generation},
    )
    await session.flush()
    if next_phase is None:
        return None
    return await create_phase_occurrence(
        session,
        workflow_id=workflow_id,
        phase_run_id=next_phase.phase_run_id,
        phase=next_phase.phase,
        expected_workflow_version=workflow.version,
        expected_generation=expected_generation + 1,
        contract_snapshot_id=next_phase.contract_snapshot_id,
        templates=next_phase.templates,
        phase_exit_criteria=next_phase.phase_exit_criteria,
    )
