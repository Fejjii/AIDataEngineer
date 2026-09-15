"""Failure injection at Interview MVP stages. Injected faults must fail closed."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.evaluation.helpers import NthFailDbt, build_eval_stack
from tests.unit.verification.test_verifier import _pack

from aide.connectors.snowflake.fake import build_fake_pair
from aide.domain.benchmark import INTERVIEW_REQUEST
from aide.domain.failures import FailureClass
from aide.domain.states import WorkflowState
from aide.domain.verification import VerifierVerdict
from aide.persistence.models import ArtifactModel, GatewayDispatchIntentModel, WorkflowModel
from aide.verification.evaluate import evaluate_verifier


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability", "connector"),
    [
        ("discover_assets", "snowflake_ro"),
        ("profile_estate", "snowflake_ro"),
    ],
)
async def test_snowflake_stage_failure_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capability: str,
    connector: str,
) -> None:
    del connector
    ro, dev = build_fake_pair()
    ro.fail_next(capability, FailureClass.CONNECTOR_FAILURE)
    supervisor, _ro, _dev, _dbt = build_eval_stack(
        session_factory, tmp_path, snowflake_ro=ro, snowflake_dev=dev
    )
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST)
    assert result.failed or result.parked
    assert result.verifier is None
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state in {WorkflowState.FAILED.value, WorkflowState.BLOCKED.value}
        intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.workflow_id == result.workflow_id
                )
            )
        ).all()
        assert intents


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "capability",
    [
        "create_transformation",
        "parse_transformation",
        "compile_transformation",
        "execute_transformation",
        "run_tests",
        "validate_interview_quality",
    ],
)
async def test_dbt_stage_failure_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    capability: str,
) -> None:
    dbt = NthFailDbt(work_root=tmp_path, fail_on={capability: 1})
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path, dbt=dbt)
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST)
    assert result.failed or result.blocked or result.parked
    assert result.verifier is None or result.verifier.verdict is VerifierVerdict.FAIL
    assert result.repair_application is None or not result.repair_application.applied


@pytest.mark.asyncio
async def test_schema_drift_diagnosis_failure_fails_closed(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    ro, dev = build_fake_pair()
    ro.fail_next("detect_schema_drift", FailureClass.CONNECTOR_FAILURE)
    supervisor, _ro, _dev, _dbt = build_eval_stack(
        session_factory, tmp_path, snowflake_ro=ro, snowflake_dev=dev
    )
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    assert result.failed or result.blocked or result.parked
    assert result.repair_application is None or not result.repair_application.applied


@pytest.mark.asyncio
async def test_repair_application_failure_fails_closed(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    dbt = NthFailDbt(work_root=tmp_path, fail_on={"create_transformation": 2})
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path, dbt=dbt)
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    assert result.failed or result.blocked or result.parked
    assert result.extra.get("applied_count", 0) != 1 or not result.execute_ok
    assert result.verifier is None or result.verifier.verdict is VerifierVerdict.FAIL


@pytest.mark.asyncio
async def test_post_repair_validation_failure_blocks(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    dbt = NthFailDbt(work_root=tmp_path, fail_on={"run_tests": 2})
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path, dbt=dbt)
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    assert result.blocked or result.failed or result.parked
    assert (
        result.block_reason
        in {
            "POST_REPAIR_VALIDATION_FAILED",
            FailureClass.CONNECTOR_FAILURE.value,
            "TESTS_FAILED",
        }
        or result.fail_reason == FailureClass.CONNECTOR_FAILURE.value
    )


def test_verifier_fails_closed_on_incomplete_evidence() -> None:
    result = evaluate_verifier(_pack(repair_applied=False))
    assert result.verdict is VerifierVerdict.FAIL
    assert result.reason_codes


@pytest.mark.asyncio
async def test_evidence_persistence_failure_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    monkeypatch.setattr(
        supervisor,
        "_persist_evidence_bundle",
        AsyncMock(side_effect=RuntimeError("injected evidence persistence failure")),
    )
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    assert result.failed or result.blocked
    assert result.fail_reason == "EVIDENCE_PERSISTENCE_FAILED" or (
        result.block_reason == "EVIDENCE_PERSISTENCE_FAILED"
    )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state in {WorkflowState.FAILED.value, WorkflowState.BLOCKED.value}
        artifacts = (
            await session.scalars(
                select(ArtifactModel).where(ArtifactModel.workflow_id == result.workflow_id)
            )
        ).all()
        assert not any(item.artifact_type == "evidence_bundle" for item in artifacts)
