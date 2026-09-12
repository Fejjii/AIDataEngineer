from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.runtime import build_offline_stack
from aide.auth.grants import GrantForgeryError
from aide.connectors.snowflake.query_tags import parse_query_tag
from aide.domain.permissions import PermissionLevel
from aide.domain.states import TaskState, WorkflowState
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskAttemptModel,
    TaskTemplateModel,
    WorkflowGrantModel,
)


@pytest.mark.asyncio
async def test_complete_offline_end_to_end_flow(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline("Investigate recent order amounts by customer")
    assert result.parked is False
    assert result.workflow_state == WorkflowState.COMPLETED.value
    assert result.catalogue is not None
    assert result.selection is not None
    assert result.generated_sql is not None
    assert result.classification is not None
    assert result.classification.is_read_only is True
    assert result.execution is not None
    assert result.validation is not None
    assert result.validation.passed is True
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
        assert parsed.attempt_id is not None
        attempt = await session.scalar(
            select(TaskAttemptModel).where(
                TaskAttemptModel.task_id == execute_task.task_id,
            )
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
        discovery = [item for item in phases if item.phase == WorkflowState.DISCOVERY.value]
        assert len(discovery) >= 2
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
        assert first.phase_run_id != second.phase_run_id
        for item in result.selection.selected:
            assert result.catalogue.contains(item.asset)


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
        workflow_templates = (
            await session.scalars(
                select(TaskTemplateModel)
                .join(PhaseRunModel, TaskTemplateModel.phase_run_id == PhaseRunModel.phase_run_id)
                .where(PhaseRunModel.workflow_id == result.workflow_id)
                .order_by(TaskTemplateModel.local_id)
            )
        ).all()
        assert [row.capability_id for row in workflow_templates] == ["discover_assets"]
        task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id
            )
        )
        assert task is not None
        assert task.status == TaskState.PARKED.value
        phases = (
            await session.scalars(
                select(PhaseRunModel).where(PhaseRunModel.workflow_id == result.workflow_id)
            )
        ).all()
        assert phases[0].status != "FAILED"


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
