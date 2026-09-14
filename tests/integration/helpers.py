from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.domain.enums import RiskLevel, TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState
from aide.domain.tasks import TaskTemplate
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.orchestration.materialization import (
    TemplateSpec,
    create_phase_occurrence,
    persist_materialized_task,
)
from aide.persistence.models import MaterializedTaskModel, TaskTemplateModel
from aide.persistence.repositories import ContractSnapshotRepository, WorkflowRepository


class SeedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


@dataclass(frozen=True)
class SeededTask:
    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    snapshot_id: UUID


async def seed_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    max_attempts: int = 2,
    local_id: str = "task",
    capability_id: str = "fake_side_effect",
) -> SeededTask:
    async with session_factory() as session, session.begin():
        workflow = await WorkflowRepository(session).add(state=WorkflowState.PLANNING)
        snapshot = ContractSnapshot(
            snapshot_id=uuid4(),
            capability_contracts=(
                CapabilityContractRef(
                    capability_id=capability_id,
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
            ),
            connector_versions={"fake": "1.0"},
        )
        await ContractSnapshotRepository(session).add(
            workflow_id=workflow.workflow_id, snapshot=snapshot
        )
        phase_run_id = uuid4()
        await create_phase_occurrence(
            session,
            workflow_id=workflow.workflow_id,
            phase_run_id=phase_run_id,
            phase=WorkflowState.EXECUTION,
            expected_workflow_version=workflow.version,
            expected_generation=1,
            contract_snapshot_id=snapshot.snapshot_id,
            templates=[
                TemplateSpec(
                    local_id=local_id,
                    capability_id=capability_id,
                    capability_contract_version=1,
                    connector_id="fake",
                    depends_on=(),
                    required_dependencies=(),
                    unresolved_inputs={"value": "payload"},
                    timeout_seconds=30,
                    max_attempts=max_attempts,
                )
            ],
        )
        template_row = await session.scalar(
            select(TaskTemplateModel).where(
                TaskTemplateModel.phase_run_id == phase_run_id,
                TaskTemplateModel.local_id == local_id,
            )
        )
        if template_row is None:
            raise AssertionError("template was not persisted")
        template = TaskTemplate(
            template_id=template_row.template_id,
            phase_run_id=phase_run_id,
            local_id=local_id,
            capability_id=capability_id,
            capability_contract_version=1,
            connector_id="fake",
            unresolved_inputs={"value": "payload"},
            timeout_seconds=30,
            max_attempts=max_attempts,
        )
        task_id = uuid4()
        await persist_materialized_task(
            session,
            template=template,
            task_id=task_id,
            workflow_id=workflow.workflow_id,
            resolved_inputs=SeedInput(value="payload"),
            input_schema=SeedInput,
            input_schema_version=1,
            output_schema_version=1,
            connector_id="fake",
            connector_version="1.0",
            target_environment=TargetEnv.DEV,
            required_permission=PermissionLevel.DEVELOPMENT_WRITE,
            risk=RiskLevel.MEDIUM,
        )
        return SeededTask(
            workflow_id=workflow.workflow_id,
            phase_run_id=phase_run_id,
            task_id=task_id,
            snapshot_id=snapshot.snapshot_id,
        )


async def get_task(
    session_factory: async_sessionmaker[AsyncSession], task_id: UUID
) -> MaterializedTaskModel:
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, task_id)
        if task is None:
            raise AssertionError("task does not exist")
        session.expunge(task)
        return task
