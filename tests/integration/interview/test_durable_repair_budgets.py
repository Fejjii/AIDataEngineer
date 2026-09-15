from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.helpers import seed_task

from aide.app.interview import build_interview_stack
from aide.app.supervisor import InterviewResult
from aide.auth.grants import GrantAuthorizer
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef, Role
from aide.domain.repair import RepairBlockReason, RepairEventKind
from aide.domain.states import WorkflowState
from aide.persistence.models import WorkflowModel
from aide.persistence.repair import RepairEventRepository


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _empty_result(workflow_id: UUID) -> InterviewResult:
    principal = PrincipalRef(
        principal_id=workflow_id,
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=workflow_id,
    )
    grants = GrantAuthorizer().authorize(
        principal,
        frozenset({PermissionLevel.READ, PermissionLevel.DEVELOPMENT_WRITE}),
        target_environment=TargetEnv.DEV,
        decided_at=_naive_now(),
    )
    return InterviewResult(
        workflow_id=workflow_id,
        principal=principal,
        grants=grants,
        extra={
            "proposal_count": 0,
            "applied_count": 0,
            "post_repair_revalidation_count": 0,
        },
    )


@pytest.mark.asyncio
async def test_persisted_application_blocks_second_repair_after_restart(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    seeded = await seed_task(session_factory, capability_id="create_transformation")
    async with session_factory() as session, session.begin():
        await RepairEventRepository(session).add(
            workflow_id=seeded.workflow_id,
            event_kind=RepairEventKind.APPLICATION,
            payload={"applied": True},
            task_id=seeded.task_id,
        )
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    result = _empty_result(seeded.workflow_id)
    result.repair_stage = "apply"
    blocked = await supervisor._enforce_repair_budget(
        result, action="apply", task_id=seeded.task_id
    )
    assert blocked
    assert result.block_reason == RepairBlockReason.SECOND_REPAIR.value
    assert result.extra.get("applied_count") == 1
    assert result.extra.get("applied_count_for_task") == 1
    assert result.extra.get("repair_budget_source") == "persisted_events"
    finalized = await supervisor._block_repair(result)
    assert finalized.blocked
    assert finalized.repair_result is not None
    assert finalized.repair_result.applied_count == 1
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        assert workflow.state == WorkflowState.BLOCKED.value


@pytest.mark.asyncio
async def test_persisted_proposal_limit_blocks_after_restart(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    seeded = await seed_task(session_factory, capability_id="propose_repair")
    async with session_factory() as session, session.begin():
        repo = RepairEventRepository(session)
        await repo.add(
            workflow_id=seeded.workflow_id,
            event_kind=RepairEventKind.PROPOSAL,
            payload={"n": 1},
            task_id=seeded.task_id,
        )
        await repo.add(
            workflow_id=seeded.workflow_id,
            event_kind=RepairEventKind.PROPOSAL,
            payload={"n": 2},
            task_id=seeded.task_id,
        )
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    result = _empty_result(seeded.workflow_id)
    blocked = await supervisor._enforce_repair_budget(
        result, action="propose", task_id=seeded.task_id
    )
    assert blocked
    assert result.block_reason == RepairBlockReason.BUDGET_EXCEEDED.value
    assert result.extra.get("proposal_count") == 2


@pytest.mark.asyncio
async def test_persisted_revalidation_limit_blocks_after_restart(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    seeded = await seed_task(session_factory, capability_id="run_tests")
    async with session_factory() as session, session.begin():
        await RepairEventRepository(session).add(
            workflow_id=seeded.workflow_id,
            event_kind=RepairEventKind.REVALIDATION,
            payload={"tests_ok": True},
            task_id=seeded.task_id,
        )
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    result = _empty_result(seeded.workflow_id)
    result.repair_stage = "post_validate"
    blocked = await supervisor._enforce_repair_budget(
        result, action="revalidate", task_id=seeded.task_id
    )
    assert blocked
    assert result.block_reason == RepairBlockReason.BUDGET_EXCEEDED.value
    assert result.extra.get("post_repair_revalidation_count") == 1
