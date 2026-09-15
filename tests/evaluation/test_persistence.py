"""Persistence and recovery around interview phases, intents, budgets, and evidence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.evaluation.helpers import build_eval_stack
from tests.integration.helpers import seed_task

from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.snowflake.fake import build_fake_pair
from aide.domain.benchmark import INTERVIEW_REQUEST
from aide.domain.failures import FailureClass
from aide.domain.repair import RepairBlockReason, RepairEventKind
from aide.domain.states import WorkflowState
from aide.persistence.models import GatewayDispatchIntentModel, WorkflowModel
from aide.persistence.repair import RepairEventRepository
from aide.persistence.repositories import ArtifactRepository


@pytest.mark.asyncio
async def test_e_rc_phase_failed_workflow_is_terminal(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    ro, dev = build_fake_pair()
    ro.fail_next("discover_assets", FailureClass.CONNECTOR_FAILURE)
    supervisor, _ro, _dev, _dbt = build_eval_stack(
        session_factory, tmp_path, snowflake_ro=ro, snowflake_dev=dev
    )
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST)
    assert result.failed
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state == WorkflowState.FAILED.value
        assert workflow.finished_at is not None
    restarted, _ro2, _dev2, _dbt2 = build_eval_stack(session_factory, tmp_path)
    with pytest.raises((RuntimeError, ValueError)):
        await restarted._create_phase(
            result,
            restarted._snapshot(),
            phase_run_id=result.workflow_id,
            phase=WorkflowState.PLANNING,
            expected_generation=99,
            templates=(),
            phase_exit_criteria=(),
        )


@pytest.mark.asyncio
async def test_e_rc_intent_failed_dispatches_are_not_left_open(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    ro, dev = build_fake_pair()
    ro.fail_next("discover_assets", FailureClass.CONNECTOR_FAILURE)
    supervisor, _ro, _dev, _dbt = build_eval_stack(
        session_factory, tmp_path, snowflake_ro=ro, snowflake_dev=dev
    )
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST)
    assert result.failed
    async with session_factory() as session:
        intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.workflow_id == result.workflow_id
                )
            )
        ).all()
        assert intents
        assert all(item.status != "DISPATCHED" for item in intents)
        assert all(item.completed_at is not None or item.status == "FAILED" for item in intents)


@pytest.mark.asyncio
async def test_e_rc_budget_survives_restart(
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
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    from tests.integration.interview.test_durable_repair_budgets import _empty_result

    result = _empty_result(seeded.workflow_id)
    result.repair_stage = "apply"
    blocked = await supervisor._enforce_repair_budget(
        result, action="apply", task_id=seeded.task_id
    )
    assert blocked
    assert result.block_reason == RepairBlockReason.SECOND_REPAIR.value
    assert result.extra.get("applied_count") == 1


@pytest.mark.asyncio
async def test_e_rc_evid_typed_evidence_survives_new_supervisor(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    assert result.verifier is not None
    digest = result.extra.get("evidence_bundle_sha256")
    assert isinstance(digest, str) and len(digest) == 64
    typed = result.extra.get("typed_evidence", {})
    assert "schema_drift" in typed
    assert "verifier_verdict" in typed
    async with session_factory() as session:
        artifacts = ArtifactRepository(session)
        rows = await artifacts.list_for_workflow(result.workflow_id)
        types = {row.artifact_type for row in rows}
        assert "evidence_bundle" in types
    restarted, _ro2, _dev2, _dbt2 = build_eval_stack(session_factory, tmp_path)
    async with session_factory() as session:
        again = await ArtifactRepository(session).list_for_workflow(result.workflow_id)
        bundle = [row for row in again if row.artifact_type == "evidence_bundle"][-1]
        assert bundle.sha256
        assert bundle.body is not None
        assert bundle.body.get("bundle_sha256") == digest
    del restarted


@pytest.mark.asyncio
async def test_e_rc_ver_verifier_pack_is_read_only(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    assert result.verifier is not None
    assert result.twin_snapshot is not None

    async def _forbid_write(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("verifier pack must not persist artifacts")

    with patch.object(ArtifactRepository, "add", new=_forbid_write):
        pack = await supervisor._verifier_pack(result)
    assert pack.workflow_id == result.workflow_id
    assert pack.twin_snapshot_id == result.twin_snapshot.twin_snapshot_id


@pytest.mark.asyncio
async def test_e_rc_ambig_fail_after_effect_reconciles_without_crash(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    dbt = FakeDbtConnector(work_root=tmp_path)
    dbt.fail_after_effect("execute_transformation")
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path, dbt=dbt)
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST)
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state in {
            WorkflowState.VALIDATION.value,
            WorkflowState.FAILED.value,
            WorkflowState.BLOCKED.value,
        }
        intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.workflow_id == result.workflow_id
                )
            )
        ).all()
        execute_intents = [
            item for item in intents if item.capability_id == "execute_transformation"
        ]
        assert execute_intents
        assert all(item.status != "DISPATCHED" for item in execute_intents)
    assert result.fail_reason != "unhandled"
    if result.execute_ok:
        assert not result.failed
    else:
        assert result.failed or result.parked or result.blocked
