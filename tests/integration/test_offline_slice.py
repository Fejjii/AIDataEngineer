from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.helpers import seed_task

from aide.app.runtime import build_offline_stack
from aide.auth.grants import GrantForgeryError
from aide.connectors.snowflake.query_tags import parse_query_tag
from aide.domain.permissions import PermissionLevel
from aide.domain.states import (
    LEGAL_TRANSITIONS,
    AttemptOutcome,
    DispatchState,
    TaskState,
    WorkflowState,
)
from aide.orchestration.worker import claim_task
from aide.persistence.models import (
    ArtifactModel,
    AuditEventModel,
    MaterializedTaskModel,
    PhaseRunModel,
    TaskAttemptModel,
    TaskTemplateModel,
    WorkflowGrantModel,
    WorkflowModel,
)


def _phase_sequence(phases: Sequence[PhaseRunModel]) -> list[str]:
    return [item.phase for item in phases]


@pytest.mark.asyncio
async def test_complete_offline_end_to_end_flow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline("Investigate recent order amounts by customer")
    assert result.parked is False
    assert result.failed is False
    assert result.workflow_state == WorkflowState.COMPLETED.value
    assert result.catalogue is not None
    assert result.selection is not None
    assert result.generated_sql is not None
    assert result.classification is not None
    assert result.classification.is_read_only is True
    assert result.execution is not None
    assert result.validation is not None
    assert result.validation.passed is True
    assert result.summary is not None
    assert result.summary.outcome == "NO_DELIVERY"
    assert result.provenance is not None
    assert result.provenance.execution_mode.value == "MOCK"
    assert result.provenance.connector_id == "snowflake_ro"
    assert PermissionLevel.READ in result.grants.effective
    assert result.query_tag is not None
    parsed = parse_query_tag(result.query_tag)
    async with session_factory() as session:
        execute_task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.capability_id == "execute_query",
            )
        )
        assert execute_task is not None
        assert execute_task.connector_id == "snowflake_ro"
        assert parsed.operation_idempotency_key == execute_task.operation_idempotency_key
        attempt = await session.scalar(
            select(TaskAttemptModel).where(TaskAttemptModel.task_id == execute_task.task_id)
        )
        assert attempt is not None
        assert parsed.attempt_id == attempt.attempt_id
        grants = (
            await session.scalars(
                select(WorkflowGrantModel).where(
                    WorkflowGrantModel.workflow_id == result.workflow_id
                )
            )
        ).all()
        assert {row.permission for row in grants} == {
            item.value for item in result.grants.effective
        }
        phases = (
            await session.scalars(
                select(PhaseRunModel)
                .where(PhaseRunModel.workflow_id == result.workflow_id)
                .order_by(PhaseRunModel.generation)
            )
        ).all()
        sequence = _phase_sequence(phases)
        assert sequence[0] == WorkflowState.PLANNING.value
        assert WorkflowState.RECEIVED.value not in sequence
        for previous, current in zip(sequence, sequence[1:], strict=False):
            assert (WorkflowState(previous), WorkflowState(current)) in LEGAL_TRANSITIONS
        assert sequence == [
            WorkflowState.PLANNING.value,
            WorkflowState.DISCOVERY.value,
            WorkflowState.PLANNING.value,
            WorkflowState.DISCOVERY.value,
            WorkflowState.PLANNING.value,
            WorkflowState.GENERATION.value,
            WorkflowState.POLICY_CHECK.value,
            WorkflowState.EXECUTION.value,
            WorkflowState.VALIDATION.value,
            WorkflowState.PLANNING.value,
            WorkflowState.DELIVERY.value,
        ]
        discovery = [item for item in phases if item.phase == WorkflowState.DISCOVERY.value]
        assert len(discovery) == 2
        first = discovery[0]
        assert "immutable_sorted_metadata_catalog" in first.phase_exit_criteria
        assert "asset_selection" not in first.phase_exit_criteria
        first_caps = [
            row.capability_id
            for row in (
                await session.scalars(
                    select(TaskTemplateModel)
                    .where(TaskTemplateModel.phase_run_id == first.phase_run_id)
                    .order_by(TaskTemplateModel.local_id)
                )
            ).all()
        ]
        assert first_caps == ["discover_assets"]
        second = discovery[1]
        second_templates = (
            await session.scalars(
                select(TaskTemplateModel)
                .where(TaskTemplateModel.phase_run_id == second.phase_run_id)
                .order_by(TaskTemplateModel.local_id)
            )
        ).all()
        describe_ids = [
            row.local_id for row in second_templates if row.capability_id == "describe_asset"
        ]
        assert describe_ids == sorted(describe_ids)
        assert len(describe_ids) == len(set(describe_ids))
        assert any(row.capability_id == "select_relevant_assets" for row in second_templates)
        generation = [item for item in phases if item.phase == WorkflowState.GENERATION.value][0]
        generation_caps = [
            row.capability_id
            for row in (
                await session.scalars(
                    select(TaskTemplateModel).where(
                        TaskTemplateModel.phase_run_id == generation.phase_run_id
                    )
                )
            ).all()
        ]
        assert "execute_query" not in generation_caps
        assert "generate_sql_query" in generation_caps
        execution = [item for item in phases if item.phase == WorkflowState.EXECUTION.value][0]
        execution_caps = [
            row.capability_id
            for row in (
                await session.scalars(
                    select(TaskTemplateModel).where(
                        TaskTemplateModel.phase_run_id == execution.phase_run_id
                    )
                )
            ).all()
        ]
        assert execution_caps == ["execute_query"]
        summary = await session.scalar(
            select(ArtifactModel).where(
                ArtifactModel.workflow_id == result.workflow_id,
                ArtifactModel.artifact_type == "WorkflowSummary",
            )
        )
        assert summary is not None
        assert summary.body is not None
        assert summary.body["outcome"] == "NO_DELIVERY"
        plan_artifacts = (
            await session.scalars(
                select(ArtifactModel).where(
                    ArtifactModel.workflow_id == result.workflow_id,
                    ArtifactModel.artifact_type == "Plan",
                )
            )
        ).all()
        assert len(plan_artifacts) >= 1
        for item in result.selection.selected:
            assert result.catalogue.contains(item.asset)


@pytest.mark.asyncio
async def test_no_received_to_discovery_transition(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline("Investigate recent order amounts by customer")
    async with session_factory() as session:
        phases = (
            await session.scalars(
                select(PhaseRunModel)
                .where(PhaseRunModel.workflow_id == result.workflow_id)
                .order_by(PhaseRunModel.generation)
            )
        ).all()
        assert phases[0].phase == WorkflowState.PLANNING.value
        assert phases[1].phase == WorkflowState.DISCOVERY.value
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state == WorkflowState.COMPLETED.value


@pytest.mark.asyncio
async def test_succeeded_tasks_have_attempt_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline("Investigate recent order amounts by customer")
    async with session_factory() as session:
        tasks = (
            await session.scalars(
                select(MaterializedTaskModel).where(
                    MaterializedTaskModel.workflow_id == result.workflow_id,
                    MaterializedTaskModel.status == TaskState.SUCCEEDED.value,
                )
            )
        ).all()
        assert tasks
        for task in tasks:
            assert task.attempt_count >= 1
            attempts = (
                await session.scalars(
                    select(TaskAttemptModel).where(TaskAttemptModel.task_id == task.task_id)
                )
            ).all()
            assert attempts
            assert any(item.outcome == AttemptOutcome.SUCCEEDED.value for item in attempts)


@pytest.mark.asyncio
async def test_authenticated_request_rejects_client_supplied_grants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    with pytest.raises(GrantForgeryError):
        await service.run_offline(
            "Investigate orders",
            client_supplied_effective=frozenset({PermissionLevel.READ}),
        )


@pytest.mark.asyncio
async def test_unavailable_connector_parks_without_invalidating_plan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline(
        "Investigate recent order amounts by customer",
        connector_unavailable=True,
    )
    assert result.parked is True
    assert result.park_reason == "CONNECTOR_UNAVAILABLE"
    assert result.workflow_state == WorkflowState.BLOCKED.value
    async with session_factory() as session:
        phases = (
            await session.scalars(
                select(PhaseRunModel)
                .where(PhaseRunModel.workflow_id == result.workflow_id)
                .order_by(PhaseRunModel.generation)
            )
        ).all()
        assert phases[0].phase == WorkflowState.PLANNING.value
        discovery = [item for item in phases if item.phase == WorkflowState.DISCOVERY.value]
        assert discovery
        templates = (
            await session.scalars(
                select(TaskTemplateModel)
                .where(TaskTemplateModel.phase_run_id == discovery[0].phase_run_id)
                .order_by(TaskTemplateModel.local_id)
            )
        ).all()
        assert [row.capability_id for row in templates] == ["discover_assets"]
        task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.capability_id == "discover_assets",
            )
        )
        assert task is not None
        assert task.status == TaskState.PARKED.value
        assert discovery[0].status != "FAILED"
        events = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.workflow_id == result.workflow_id,
                    AuditEventModel.event_type == "TASK_PARKED",
                )
            )
        ).all()
        assert events
        assert events[0].payload.get("routing") == "PARK"
        assert "CONNECTOR_UNAVAILABLE" in events[0].payload.get("reasons", [])
        attempts = await _attempts(session, task.task_id)
        _assert_policy_disposition_is_terminal(task, session_attempts=attempts)


@pytest.mark.asyncio
async def test_scope_violation_fail_closed_persists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline(
        "Investigate recent order amounts by customer",
        force_scope_violation=True,
    )
    assert result.failed is True
    assert result.parked is False
    assert result.workflow_state == WorkflowState.FAILED.value
    async with session_factory() as session:
        task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.status == TaskState.FAILED.value,
            )
        )
        assert task is not None
        assert task.lease_owner is None
        assert task.active_attempt_id is None
        assert task.status == TaskState.FAILED.value
        events = (
            await session.scalars(
                select(AuditEventModel).where(
                    AuditEventModel.workflow_id == result.workflow_id,
                    AuditEventModel.event_type == "POLICY_DENIED",
                )
            )
        ).all()
        assert events
        assert events[0].payload.get("routing") == "FAIL_CLOSED"
        assert "SCOPE_VIOLATION" in events[0].payload.get("reasons", [])
        parked = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.status == TaskState.PARKED.value,
            )
        )
        assert parked is None
        attempts = await _attempts(session, task.task_id)
        _assert_policy_disposition_is_terminal(task, session_attempts=attempts)


@pytest.mark.asyncio
async def test_contract_version_unavailable_parks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline(
        "Investigate recent order amounts by customer",
        pin_unknown_capability=True,
    )
    assert result.parked is True
    assert result.park_reason == "CONTRACT_VERSION_UNAVAILABLE"
    assert result.workflow_state == WorkflowState.BLOCKED.value
    async with session_factory() as session:
        task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.status == TaskState.PARKED.value,
            )
        )
        assert task is not None
        assert task.attempt_count == 0
        assert task.active_attempt_id is None
        assert task.lease_owner is None
        assert task.lease_expires_at is None
        assert task.recovery_owner is None
        assert task.recovery_lease_expires_at is None
        attempts = await _attempts(session, task.task_id)
        assert attempts == []


@pytest.mark.asyncio
async def test_claim_filters_do_not_steal_foreign_workflow_or_phase(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    foreign = await seed_task(session_factory, local_id="foreign")
    other_phase = await seed_task(session_factory, local_id="other-phase")
    service = build_offline_stack(session_factory)
    result = await service.run_offline("Investigate recent order amounts by customer")
    assert result.workflow_state == WorkflowState.COMPLETED.value
    async with session_factory() as session:
        foreign_task = await session.get(MaterializedTaskModel, foreign.task_id)
        other_task = await session.get(MaterializedTaskModel, other_phase.task_id)
        assert foreign_task is not None
        assert other_task is not None
        assert foreign_task.status == TaskState.READY.value
        assert foreign_task.attempt_count == 0
        assert other_task.status == TaskState.READY.value
        assert other_task.attempt_count == 0
        owned = (
            await session.scalars(
                select(MaterializedTaskModel).where(
                    MaterializedTaskModel.workflow_id == result.workflow_id
                )
            )
        ).all()
        assert all(item.workflow_id == result.workflow_id for item in owned)
    async with session_factory() as session, session.begin():
        leftover_claim = await claim_task(
            session,
            owner="post-slice",
            now=datetime(2026, 1, 1),
            lease_duration=timedelta(seconds=5),
            workflow_id=foreign.workflow_id,
        )
        assert leftover_claim is not None
        assert leftover_claim.task_id == foreign.task_id


@pytest.mark.asyncio
async def test_run_phase_cannot_claim_another_phase_occurrence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await seed_task(session_factory, local_id="alpha")
    second = await seed_task(session_factory, local_id="beta")
    now = datetime(2026, 1, 1)
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session,
            owner="slice-test",
            now=now,
            lease_duration=timedelta(seconds=5),
            workflow_id=first.workflow_id,
            phase_run_id=first.phase_run_id,
        )
        assert claim is not None
        assert claim.task_id == first.task_id
        stolen = await claim_task(
            session,
            owner="slice-test",
            now=now,
            lease_duration=timedelta(seconds=5),
            workflow_id=first.workflow_id,
            phase_run_id=second.phase_run_id,
        )
        assert stolen is None
    async with session_factory() as session:
        leftover = await session.get(MaterializedTaskModel, second.task_id)
        assert leftover is not None
        assert leftover.status == TaskState.READY.value
        assert leftover.attempt_count == 0


async def _attempts(session: AsyncSession, task_id: UUID) -> list[TaskAttemptModel]:
    rows = (
        await session.scalars(select(TaskAttemptModel).where(TaskAttemptModel.task_id == task_id))
    ).all()
    return list(rows)


def _assert_policy_disposition_is_terminal(
    task: MaterializedTaskModel,
    *,
    session_attempts: Sequence[TaskAttemptModel],
) -> None:
    assert task.active_attempt_id is None
    assert task.lease_owner is None
    assert task.lease_expires_at is None
    assert task.recovery_owner is None
    assert task.recovery_lease_expires_at is None
    assert session_attempts
    for attempt in session_attempts:
        assert attempt.outcome == AttemptOutcome.FAILED.value
        assert attempt.outcome != AttemptOutcome.STARTED.value
        assert attempt.finished_at is not None
        assert attempt.dispatch_state == DispatchState.NOT_DISPATCHED.value
