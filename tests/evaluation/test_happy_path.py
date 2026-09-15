"""E-HP-01 happy path, human interventions, and observed performance baseline."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.evaluation.helpers import build_eval_stack

from aide.domain.benchmark import INTERVIEW_REQUEST
from aide.domain.failures import FailureClass
from aide.domain.repair import ACCEPTED_FROM_COLUMN, ACCEPTED_TO_COLUMN
from aide.domain.states import WorkflowState
from aide.domain.verification import VerifierVerdict
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.persistence.models import GatewayDispatchIntentModel, WorkflowModel

# MVP004 AT-23 observed ~14s. Ten times that is a hang detector, not an SLA.
OBSERVED_BASELINE_MS = 14_000
HANG_MULTIPLIER = 10


@pytest.mark.asyncio
async def test_e_hp_01_offline_closed_loop_pass_and_performance(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    started = time.perf_counter()
    result = await supervisor.run_customer_revenue(INTERVIEW_REQUEST, include_schema_drift=True)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    assert result.fail_reason is None, result.fail_reason
    assert result.block_reason is None, result.block_reason
    assert not result.failed
    assert not result.blocked
    assert result.failure_class is FailureClass.SCHEMA_MISMATCH
    assert result.proposal is not None
    assert result.proposal.from_column == ACCEPTED_FROM_COLUMN
    assert result.proposal.to_column == ACCEPTED_TO_COLUMN
    assert result.repair_application is not None
    assert result.repair_application.applied
    assert result.extra.get("applied_count") == 1
    assert result.parse_ok
    assert result.compile_ok
    assert result.execute_ok
    assert result.tests_ok
    assert result.quality is not None
    assert result.quality.passed
    ids = {item.check_id: item.passed for item in result.quality.checks}
    assert ids.get("invoice_line_sum_matches_mart")
    assert ids.get("payment_sum_matches_mart")
    assert result.verifier is not None
    assert result.verifier.verdict is VerifierVerdict.PASS
    assert result.generated is not None
    assert set(REQUIRED_DEMO_MODELS).issubset(set(result.generated.model_names))
    assert result.extra.get("human_intervention_count", 0) == 0
    assert elapsed_ms > 0
    assert elapsed_ms < OBSERVED_BASELINE_MS * HANG_MULTIPLIER
    result.extra["eval_wall_clock_ms"] = elapsed_ms
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state in {
            WorkflowState.VALIDATION.value,
            WorkflowState.COMPLETED.value,
        }
        intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.workflow_id == result.workflow_id
                )
            )
        ).all()
        assert intents
        assert any(item.action == "EXECUTE" and item.status == "SUCCEEDED" for item in intents)
        assert all(item.status != "DISPATCHED" or item.completed_at is None for item in intents)
