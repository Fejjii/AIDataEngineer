"""Pinned contract availability checks at scheduling and resume boundaries."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.registry import ConnectorRegistry
from aide.domain.states import TaskState, WorkflowState
from aide.domain.versions import ContractSnapshot
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    ContractSnapshotModel,
    MaterializedTaskModel,
    PhaseRunModel,
    WorkflowModel,
)
from aide.policy.versions import emit_contract_version_unavailable


async def evaluate_pinned_contract(
    session: AsyncSession,
    *,
    task_id: UUID,
    capabilities: CapabilityRegistry,
    connectors: ConnectorRegistry,
) -> bool:
    """Park unavailable pinned work; make restored compatible work claimable."""
    task = await session.get(MaterializedTaskModel, task_id, with_for_update=True)
    if task is None:
        raise LookupError("task does not exist")
    phase_run = await session.get(PhaseRunModel, task.phase_run_id)
    if phase_run is None:
        raise LookupError("phase occurrence does not exist")
    row = await session.get(ContractSnapshotModel, phase_run.contract_snapshot_id)
    if row is None:
        raise LookupError("contract snapshot does not exist")
    snapshot = ContractSnapshot.model_validate(
        {
            "snapshot_id": row.snapshot_id,
            "capability_contracts": row.capability_contracts,
            "connector_versions": row.connector_versions,
        }
    )
    reason = emit_contract_version_unavailable(
        snapshot,
        capabilities=capabilities,
        connectors=connectors,
    )
    workflow = await session.scalar(
        select(WorkflowModel).where(WorkflowModel.workflow_id == task.workflow_id).with_for_update()
    )
    if workflow is None:
        raise LookupError("workflow does not exist")
    if reason is None:
        if (
            task.status == TaskState.PARKED.value
            and task.disposition_reason == "CONTRACT_VERSION_UNAVAILABLE"
        ):
            task.status = TaskState.READY.value
            task.failure_classification = None
            task.disposition_reason = None
            workflow.state = phase_run.phase
            workflow.blocked_from_phase = None
            workflow.version += 1
            await append_audit_event(
                session,
                workflow_id=task.workflow_id,
                phase_run_id=task.phase_run_id,
                task_id=task.task_id,
                event_type="CONTRACT_VERSION_RESTORED",
                payload={"snapshot_id": str(snapshot.snapshot_id)},
            )
        await session.flush()
        return True
    task.status = TaskState.PARKED.value
    task.failure_classification = "POLICY_DENIED"
    task.disposition_reason = reason.value
    workflow.blocked_from_phase = phase_run.phase
    workflow.state = WorkflowState.BLOCKED.value
    workflow.version += 1
    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        event_type="CONTRACT_VERSION_UNAVAILABLE",
        payload={"snapshot_id": str(snapshot.snapshot_id)},
    )
    await session.flush()
    return False
