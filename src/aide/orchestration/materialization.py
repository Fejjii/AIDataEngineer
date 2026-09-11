"""Transactional phase occurrence and operation materialization."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.enums import RiskLevel, TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import PhaseRunStatus, TaskState, WorkflowState
from aide.domain.tasks import MaterializedTask, TaskTemplate, materialize_task
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskTemplateModel,
    WorkflowModel,
)


class ConcurrentStateError(RuntimeError):
    """Raised when an expected workflow version or phase generation is stale."""


PHASE_CREATION_FORBIDDEN_STATES = frozenset(
    {
        WorkflowState.CANCEL_REQUESTED.value,
        WorkflowState.CANCELLING.value,
        WorkflowState.CANCELLED.value,
        WorkflowState.COMPLETED.value,
        WorkflowState.FAILED.value,
    }
)


def advisory_lock_key(workflow_id: UUID) -> int:
    """Produce a stable signed bigint for PostgreSQL advisory transaction locks."""
    digest = hashlib.blake2b(workflow_id.bytes, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def acquire_workflow_lock(session: AsyncSession, workflow_id: UUID) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": advisory_lock_key(workflow_id)},
    )


@dataclass(frozen=True)
class TemplateSpec:
    local_id: str
    capability_id: str
    capability_contract_version: int
    connector_id: str | None
    depends_on: tuple[str, ...]
    required_dependencies: tuple[str, ...]
    unresolved_inputs: dict[str, object]
    timeout_seconds: int
    max_attempts: int
    created_by: str = "SYSTEM"


async def create_phase_occurrence(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    phase_run_id: UUID,
    phase: WorkflowState,
    expected_workflow_version: int,
    expected_generation: int,
    contract_snapshot_id: UUID,
    templates: Sequence[TemplateSpec],
    phase_exit_criteria: Sequence[str] = (),
) -> PhaseRunModel:
    """Create one phase occurrence and its immutable template DAG atomically."""
    await acquire_workflow_lock(session, workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError(f"workflow {workflow_id} does not exist")
    if workflow.version != expected_workflow_version:
        raise ConcurrentStateError("workflow version changed")
    ensure_phase_creation_allowed(workflow)
    latest_generation = await session.scalar(
        select(func.max(PhaseRunModel.generation)).where(PhaseRunModel.workflow_id == workflow_id)
    )
    actual_next = (latest_generation or 0) + 1
    if expected_generation != actual_next:
        raise ConcurrentStateError(
            f"expected generation {expected_generation}, next is {actual_next}"
        )
    local_ids = [item.local_id for item in templates]
    if local_ids != sorted(local_ids) or len(local_ids) != len(set(local_ids)):
        raise ValueError("templates must be unique and sorted by local_id")
    local_id_set = set(local_ids)
    for item in templates:
        if not set(item.depends_on).issubset(local_id_set):
            raise ValueError("template dependencies must stay inside the phase occurrence")
        if not set(item.required_dependencies).issubset(set(item.depends_on)):
            raise ValueError("required_dependencies must be a subset of depends_on")

    phase_run = PhaseRunModel(
        phase_run_id=phase_run_id,
        workflow_id=workflow_id,
        phase=phase.value,
        generation=expected_generation,
        contract_snapshot_id=contract_snapshot_id,
        phase_exit_criteria=list(phase_exit_criteria),
        status=PhaseRunStatus.ACTIVE.value,
    )
    session.add(phase_run)
    await session.flush()
    session.add_all(
        [
            TaskTemplateModel(
                phase_run_id=phase_run_id,
                local_id=item.local_id,
                capability_id=item.capability_id,
                capability_contract_version=item.capability_contract_version,
                connector_id=item.connector_id,
                depends_on=list(item.depends_on),
                required_dependencies=list(item.required_dependencies),
                unresolved_inputs=item.unresolved_inputs,
                timeout_seconds=item.timeout_seconds,
                max_attempts=item.max_attempts,
                created_by=item.created_by,
            )
            for item in templates
        ]
    )
    workflow.active_phase_run_id = phase_run_id
    workflow.state = phase.value
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        phase_run_id=phase_run_id,
        event_type="PLAN_ACCEPTED",
        payload={
            "generation": expected_generation,
            "phase": phase.value,
            "template_local_ids": local_ids,
        },
    )
    await session.flush()
    return phase_run


def ensure_phase_creation_allowed(workflow: WorkflowModel) -> None:
    """Reject phase creation or advancement after cancellation or terminalization."""
    if workflow.state in PHASE_CREATION_FORBIDDEN_STATES:
        raise ValueError(f"workflow state {workflow.state} forbids phase creation")


async def resume_existing_phase(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    expected_workflow_version: int,
) -> PhaseRunModel:
    """Resume parked or approval-waiting work without allocating an occurrence."""
    await acquire_workflow_lock(session, workflow_id)
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id).with_for_update()
    )
    if workflow is None or workflow.active_phase_run_id is None:
        raise LookupError("workflow has no active phase occurrence")
    if workflow.version != expected_workflow_version:
        raise ConcurrentStateError("workflow version changed")
    if workflow.state not in {
        WorkflowState.BLOCKED.value,
        WorkflowState.APPROVAL_REQUIRED.value,
    }:
        raise ValueError("only parked or approval-waiting work can resume")
    phase_run = await session.scalar(
        select(PhaseRunModel)
        .where(PhaseRunModel.phase_run_id == workflow.active_phase_run_id)
        .with_for_update()
    )
    if phase_run is None:
        raise LookupError("active phase occurrence does not exist")
    if workflow.state == WorkflowState.BLOCKED.value:
        tasks = (
            await session.scalars(
                select(MaterializedTaskModel).where(
                    MaterializedTaskModel.phase_run_id == phase_run.phase_run_id,
                    MaterializedTaskModel.status == TaskState.PARKED.value,
                )
            )
        ).all()
        for task in tasks:
            task.status = TaskState.READY.value
            task.failure_classification = None
            task.disposition_reason = None
    workflow.state = phase_run.phase
    workflow.blocked_from_phase = None
    workflow.version += 1
    phase_run.status = PhaseRunStatus.ACTIVE.value
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        phase_run_id=phase_run.phase_run_id,
        event_type="PHASE_RESUMED",
        payload={"generation": phase_run.generation},
    )
    await session.flush()
    return phase_run


async def persist_materialized_task(
    session: AsyncSession,
    *,
    template: TaskTemplate,
    task_id: UUID,
    workflow_id: UUID,
    resolved_inputs: BaseModel | dict[str, object],
    input_schema: type[BaseModel],
    input_schema_version: int,
    output_schema_version: int,
    connector_id: str | None,
    connector_version: str | None,
    target_environment: TargetEnv | None,
    required_permission: PermissionLevel,
    risk: RiskLevel,
    validators: tuple[str, ...] = (),
) -> MaterializedTaskModel:
    """Validate and persist operation identity plus audit in the same transaction."""
    domain_task = materialize_task(
        template,
        task_id=task_id,
        workflow_id=workflow_id,
        resolved_inputs=resolved_inputs,
        input_schema=input_schema,
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
        connector_id=connector_id,
        connector_version=connector_version,
        target_environment=target_environment,
        required_permission=required_permission,
        risk=risk,
        validators=validators,
    )
    row = _to_model(domain_task)
    session.add(row)
    await append_audit_event(
        session,
        workflow_id=workflow_id,
        phase_run_id=template.phase_run_id,
        task_id=task_id,
        operation_idempotency_key=domain_task.operation_idempotency_key,
        event_type="OPERATION_MATERIALIZED",
        payload={
            "local_id": template.local_id,
            "resolved_input_digest": domain_task.resolved_input_digest,
        },
    )
    await session.flush()
    return row


def _to_model(task: MaterializedTask) -> MaterializedTaskModel:
    return MaterializedTaskModel(
        task_id=task.task_id,
        template_id=task.template_id,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        local_id=task.local_id,
        capability_id=task.capability_id,
        capability_contract_version=task.capability_contract_version,
        input_schema_version=task.input_schema_version,
        output_schema_version=task.output_schema_version,
        connector_id=task.connector_id,
        connector_version=task.connector_version,
        target_environment=(
            task.target_environment.value if task.target_environment is not None else None
        ),
        resolved_inputs=task.resolved_inputs,
        resolved_input_digest=task.resolved_input_digest,
        operation_idempotency_key=task.operation_idempotency_key,
        required_permission=task.required_permission.value,
        risk=task.risk.value,
        timeout_seconds=task.timeout_seconds,
        max_attempts=task.max_attempts,
        validators=list(task.validators),
        status=TaskState.READY.value,
    )
