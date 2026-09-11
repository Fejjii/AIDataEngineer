from __future__ import annotations

import asyncio
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.helpers import seed_task

from aide.domain.states import PhaseRunStatus, TaskState, WorkflowState
from aide.orchestration.cancellation import request_cancellation
from aide.orchestration.coordination import (
    NextPhase,
    propagate_required_dependency_failures,
    reduce_and_advance,
)
from aide.orchestration.materialization import (
    ConcurrentStateError,
    create_phase_occurrence,
    resume_existing_phase,
)
from aide.persistence.models import (
    AuditEventModel,
    MaterializedTaskModel,
    PhaseRunModel,
    TaskTemplateModel,
    TemplateDispositionModel,
    WorkflowModel,
)


@pytest.mark.asyncio
async def test_two_coordinators_create_one_next_phase_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert task is not None and workflow is not None
        task.status = TaskState.SUCCEEDED.value
        expected_version = workflow.version

    async def coordinate(phase_run_id: UUID) -> object:
        async with session_factory() as session, session.begin():
            return await reduce_and_advance(
                session,
                workflow_id=seeded.workflow_id,
                expected_workflow_version=expected_version,
                expected_generation=1,
                next_phase=NextPhase(
                    phase_run_id=phase_run_id,
                    phase=WorkflowState.VALIDATION,
                    contract_snapshot_id=seeded.snapshot_id,
                    templates=(),
                ),
            )

    results = await asyncio.gather(
        coordinate(uuid4()),
        coordinate(uuid4()),
        return_exceptions=True,
    )
    assert sum(isinstance(result, PhaseRunModel) for result in results) == 1
    assert sum(isinstance(result, ConcurrentStateError) for result in results) == 1
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(PhaseRunModel)
            .where(
                PhaseRunModel.workflow_id == seeded.workflow_id,
                PhaseRunModel.generation == 2,
            )
        )
        assert count == 1


@pytest.mark.parametrize(
    ("waiting_state", "task_state"),
    [
        (WorkflowState.BLOCKED, TaskState.PARKED),
        (WorkflowState.APPROVAL_REQUIRED, TaskState.AWAITING_APPROVAL),
    ],
)
@pytest.mark.asyncio
async def test_resume_waiting_phase_does_not_allocate_second_occurrence(
    session_factory: async_sessionmaker[AsyncSession],
    waiting_state: WorkflowState,
    task_state: TaskState,
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        phase = await session.get(PhaseRunModel, seeded.phase_run_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert workflow is not None and phase is not None and task is not None
        workflow.state = waiting_state.value
        workflow.version += 1
        phase.status = PhaseRunStatus.BLOCKED.value
        task.status = task_state.value
        expected_version = workflow.version

    async with session_factory() as session, session.begin():
        resumed = await resume_existing_phase(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
        )
        assert resumed.phase_run_id == seeded.phase_run_id
    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(PhaseRunModel)
            .where(PhaseRunModel.workflow_id == seeded.workflow_id)
        )
        assert count == 1


@pytest.mark.asyncio
async def test_required_dependency_failure_cascades_deterministically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, local_id="a_upstream")
    async with session_factory() as session, session.begin():
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        task.status = TaskState.FAILED.value
        session.add(
            TaskTemplateModel(
                phase_run_id=seeded.phase_run_id,
                local_id="b_downstream",
                capability_id="fake_side_effect",
                capability_contract_version=1,
                connector_id="fake",
                depends_on=["a_upstream"],
                required_dependencies=["a_upstream"],
                unresolved_inputs={"value": {"$from": "a_upstream"}},
                timeout_seconds=30,
                max_attempts=1,
                created_by="SYSTEM",
            )
        )
    async with session_factory() as session, session.begin():
        created = await propagate_required_dependency_failures(
            session, phase_run_id=seeded.phase_run_id
        )
        assert created == 1
    async with session_factory() as session:
        disposition = await session.scalar(
            select(TemplateDispositionModel).where(
                TemplateDispositionModel.phase_run_id == seeded.phase_run_id
            )
        )
        assert disposition is not None
        assert disposition.status == TaskState.SKIPPED.value
        assert disposition.upstream_local_id == "a_upstream"


@pytest.mark.asyncio
async def test_transaction_rollback_leaves_no_partial_phase_persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id = uuid4()
    with pytest.raises(RuntimeError, match="rollback"):
        async with session_factory() as session, session.begin():
            session.add(
                WorkflowModel(
                    workflow_id=workflow_id,
                    state=WorkflowState.PLANNING.value,
                )
            )
            await session.flush()
            raise RuntimeError("rollback")
    async with session_factory() as session:
        assert await session.get(WorkflowModel, workflow_id) is None


@pytest.mark.asyncio
async def test_generation_must_be_monotonic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        version = workflow.version
    with pytest.raises(ConcurrentStateError, match="next is 2"):
        async with session_factory() as session, session.begin():
            await create_phase_occurrence(
                session,
                workflow_id=seeded.workflow_id,
                phase_run_id=uuid4(),
                phase=WorkflowState.VALIDATION,
                expected_workflow_version=version,
                expected_generation=3,
                contract_snapshot_id=seeded.snapshot_id,
                templates=(),
            )


@pytest.mark.parametrize(
    "forbidden_state",
    [
        WorkflowState.CANCEL_REQUESTED,
        WorkflowState.CANCELLING,
        WorkflowState.CANCELLED,
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
    ],
)
@pytest.mark.asyncio
async def test_phase_creation_rejects_cancellation_and_terminal_states(
    session_factory: async_sessionmaker[AsyncSession],
    forbidden_state: WorkflowState,
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        workflow.state = forbidden_state.value
        workflow.version += 1
        expected_version = workflow.version

    with pytest.raises(ValueError, match="forbids phase creation"):
        async with session_factory() as session, session.begin():
            await create_phase_occurrence(
                session,
                workflow_id=seeded.workflow_id,
                phase_run_id=uuid4(),
                phase=WorkflowState.VALIDATION,
                expected_workflow_version=expected_version,
                expected_generation=2,
                contract_snapshot_id=seeded.snapshot_id,
                templates=(),
            )

    async with session_factory() as session:
        phase_count = await session.scalar(
            select(func.count())
            .select_from(PhaseRunModel)
            .where(PhaseRunModel.workflow_id == seeded.workflow_id)
        )
        plan_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(
                AuditEventModel.workflow_id == seeded.workflow_id,
                AuditEventModel.event_type == "PLAN_ACCEPTED",
            )
        )
        assert phase_count == 1
        assert plan_count == 1


@pytest.mark.asyncio
async def test_stale_and_current_coordinators_cannot_advance_after_cancellation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert task is not None and workflow is not None
        task.status = TaskState.SUCCEEDED.value
        stale_version = workflow.version

    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=stale_version,
            actor_principal_id=uuid4(),
            reason="stop before advancement",
            now=datetime(2026, 9, 11, 18, 0, 0),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        current_version = workflow.version

    async def coordinate(expected_version: int) -> object:
        try:
            async with session_factory() as session, session.begin():
                return await reduce_and_advance(
                    session,
                    workflow_id=seeded.workflow_id,
                    expected_workflow_version=expected_version,
                    expected_generation=1,
                    next_phase=NextPhase(
                        phase_run_id=uuid4(),
                        phase=WorkflowState.VALIDATION,
                        contract_snapshot_id=seeded.snapshot_id,
                        templates=(),
                    ),
                )
        except (ConcurrentStateError, ValueError) as exc:
            return exc

    results = await asyncio.gather(
        coordinate(stale_version),
        coordinate(current_version),
    )
    assert any(isinstance(result, ConcurrentStateError) for result in results)
    assert any(isinstance(result, ValueError) for result in results)
    async with session_factory() as session:
        phase_count = await session.scalar(
            select(func.count())
            .select_from(PhaseRunModel)
            .where(PhaseRunModel.workflow_id == seeded.workflow_id)
        )
        plan_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(
                AuditEventModel.workflow_id == seeded.workflow_id,
                AuditEventModel.event_type == "PLAN_ACCEPTED",
            )
        )
        assert phase_count == 1
        assert plan_count == 1
