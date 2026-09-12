from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.runtime import build_offline_stack
from aide.domain.states import AttemptOutcome, DispatchState, TaskState, WorkflowState
from aide.persistence.models import ArtifactModel, MaterializedTaskModel, TaskAttemptModel

_OWNED_TYPES = frozenset({"RequirementSpec", "Plan", "ValidationReport", "WorkflowSummary"})
_REQUEST = "Investigate recent order amounts by customer"
_DATABASE_URL = os.getenv(
    "AIDE_TEST_DATABASE_URL",
    "postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev",
)


def _artifact_index(
    rows: list[ArtifactModel],
) -> dict[str, list[ArtifactModel]]:
    grouped: dict[str, list[ArtifactModel]] = {}
    for row in rows:
        grouped.setdefault(row.artifact_type, []).append(row)
    return grouped


@pytest.mark.asyncio
async def test_two_identical_offline_workflows_keep_artifact_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    first = await service.run_offline(_REQUEST)
    second = await service.run_offline(_REQUEST)
    assert first.workflow_state == WorkflowState.COMPLETED.value
    assert second.workflow_state == WorkflowState.COMPLETED.value
    assert first.workflow_id != second.workflow_id
    async with session_factory() as session:
        first_rows = list(
            (
                await session.scalars(
                    select(ArtifactModel).where(ArtifactModel.workflow_id == first.workflow_id)
                )
            ).all()
        )
        second_rows = list(
            (
                await session.scalars(
                    select(ArtifactModel).where(ArtifactModel.workflow_id == second.workflow_id)
                )
            ).all()
        )
        first_index = _artifact_index(first_rows)
        second_index = _artifact_index(second_rows)
        assert set(first_index) >= _OWNED_TYPES
        assert set(second_index) >= _OWNED_TYPES
        for artifact_type in _OWNED_TYPES:
            left = first_index[artifact_type][0]
            right = second_index[artifact_type][0]
            assert left.workflow_id == first.workflow_id
            assert right.workflow_id == second.workflow_id
            assert left.artifact_id != right.artifact_id
        for artifact_type in ("RequirementSpec", "Plan", "ValidationReport"):
            left = first_index[artifact_type][0]
            right = second_index[artifact_type][0]
            assert left.sha256 == right.sha256
            assert left.body == right.body
        first_summary = first_index["WorkflowSummary"][0]
        second_summary = second_index["WorkflowSummary"][0]
        assert first_summary.body is not None
        assert second_summary.body is not None
        assert first_summary.body["workflow_id"] == str(first.workflow_id)
        assert second_summary.body["workflow_id"] == str(second.workflow_id)
        assert first_summary.sha256 != second_summary.sha256
        plan_tasks = list(
            (
                await session.scalars(
                    select(MaterializedTaskModel).where(
                        MaterializedTaskModel.workflow_id == first.workflow_id,
                        MaterializedTaskModel.capability_id == "plan_phase",
                    )
                )
            ).all()
        )
        assert plan_tasks
        for task in plan_tasks:
            grants = task.resolved_inputs["constraints"]["effective_grants"]
            assert grants == ["READ"]
        writes = list(
            (
                await session.scalars(
                    select(MaterializedTaskModel).where(
                        MaterializedTaskModel.capability_id == "create_dataset",
                    )
                )
            ).all()
        )
        assert writes == []


@pytest.mark.asyncio
async def test_concurrent_identical_offline_workflows_keep_artifact_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_service = build_offline_stack(session_factory)
    second_service = build_offline_stack(session_factory)
    first, second = await asyncio.gather(
        first_service.run_offline(_REQUEST),
        second_service.run_offline(_REQUEST),
    )
    assert first.workflow_state == WorkflowState.COMPLETED.value
    assert second.workflow_state == WorkflowState.COMPLETED.value
    assert first.workflow_id != second.workflow_id
    async with session_factory() as session:
        first_rows = list(
            (
                await session.scalars(
                    select(ArtifactModel).where(ArtifactModel.workflow_id == first.workflow_id)
                )
            ).all()
        )
        second_rows = list(
            (
                await session.scalars(
                    select(ArtifactModel).where(ArtifactModel.workflow_id == second.workflow_id)
                )
            ).all()
        )
        assert {row.artifact_type for row in first_rows} >= _OWNED_TYPES
        assert {row.artifact_type for row in second_rows} >= _OWNED_TYPES


@pytest.mark.asyncio
async def test_connector_unavailable_leaves_no_external_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline(_REQUEST, connector_unavailable=True)
    assert result.parked is True
    async with session_factory() as session:
        task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.capability_id == "discover_assets",
            )
        )
        assert task is not None
        assert task.status == TaskState.PARKED.value
        attempts = list(
            (
                await session.scalars(
                    select(TaskAttemptModel).where(TaskAttemptModel.task_id == task.task_id)
                )
            ).all()
        )
        assert attempts
        for attempt in attempts:
            assert attempt.dispatch_state == DispatchState.NOT_DISPATCHED.value
            assert attempt.outcome == AttemptOutcome.FAILED.value
            assert attempt.finished_at is not None


@pytest.mark.asyncio
async def test_scope_violation_leaves_no_external_dispatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    result = await service.run_offline(_REQUEST, force_scope_violation=True)
    assert result.failed is True
    async with session_factory() as session:
        task = await session.scalar(
            select(MaterializedTaskModel).where(
                MaterializedTaskModel.workflow_id == result.workflow_id,
                MaterializedTaskModel.status == TaskState.FAILED.value,
            )
        )
        assert task is not None
        attempts = list(
            (
                await session.scalars(
                    select(TaskAttemptModel).where(TaskAttemptModel.task_id == task.task_id)
                )
            ).all()
        )
        assert attempts
        for attempt in attempts:
            assert attempt.dispatch_state == DispatchState.NOT_DISPATCHED.value
            assert attempt.outcome == AttemptOutcome.FAILED.value
            assert attempt.finished_at is not None


@pytest.mark.asyncio
async def test_artifact_uniqueness_migration_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del session_factory
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", _DATABASE_URL)
    try:
        command.downgrade(config, "9c3045032ed2")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        command.upgrade(config, "head")
