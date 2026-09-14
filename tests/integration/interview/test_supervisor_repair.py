from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.interview import build_interview_stack
from aide.app.supervisor import LEGAL_INTERVIEW_PHASES
from aide.domain.failures import FailureClass
from aide.domain.states import WorkflowState
from aide.domain.verification import VerifierVerdict
from aide.persistence.models import RepairEventModel, WorkflowModel


@pytest.mark.asyncio
async def test_accepted_schema_drift_repair_and_verifier_pass(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    result = await supervisor.run_customer_revenue(
        "Build a customer revenue analytical data product from CRM and billing data.",
        include_schema_drift=True,
    )
    assert result.fail_reason is None, result.fail_reason
    assert result.block_reason is None, result.block_reason
    assert not result.failed
    assert not result.parked
    assert not result.blocked
    assert result.workflow_states[: len(LEGAL_INTERVIEW_PHASES)] == [
        phase.value for phase in LEGAL_INTERVIEW_PHASES
    ]
    assert result.workflow_states[len(LEGAL_INTERVIEW_PHASES) :] == [
        WorkflowState.REPAIR.value,
        WorkflowState.EXECUTION.value,
        WorkflowState.VALIDATION.value,
    ]
    assert result.failure_class is FailureClass.SCHEMA_MISMATCH
    assert result.drift is not None
    assert result.drift.authoritative
    assert result.proposal is not None
    assert result.repair_validation is not None
    assert result.repair_validation.allowed
    assert result.repair_application is not None
    assert result.repair_application.applied
    assert result.before_artifact_hash
    assert result.after_artifact_hash
    assert result.before_artifact_hash != result.after_artifact_hash
    assert result.parse_ok
    assert result.compile_ok
    assert result.execute_ok
    assert result.tests_ok
    assert result.quality is not None
    assert result.quality.passed
    assert result.verifier is not None
    assert result.verifier.verdict is VerifierVerdict.PASS
    assert result.extra.get("applied_count") == 1
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state == WorkflowState.VALIDATION.value
        events = (
            await session.scalars(
                select(RepairEventModel).where(RepairEventModel.workflow_id == result.workflow_id)
            )
        ).all()
        kinds = {item.event_kind for item in events}
        assert "PROPOSAL" in kinds
        assert "VALIDATION" in kinds
        assert "APPLICATION" in kinds
        assert "VERDICT" in kinds
        assert sum(1 for item in events if item.event_kind == "APPLICATION") == 1
