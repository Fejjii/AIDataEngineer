from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.interview import build_interview_stack
from aide.app.supervisor import LEGAL_INTERVIEW_PHASES
from aide.auth.grants import GrantForgeryError
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.persistence.models import GatewayDispatchIntentModel, WorkflowModel


@pytest.mark.asyncio
async def test_client_supplied_grants_are_rejected(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    with pytest.raises(GrantForgeryError):
        await supervisor.run_customer_revenue(
            "Build a customer revenue analytical data product",
            client_supplied_effective=frozenset({PermissionLevel.READ}),
        )


@pytest.mark.asyncio
async def test_fixed_customer_revenue_request_completes_pre_drift_workflow(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    result = await supervisor.run_customer_revenue(
        "Build a customer revenue analytical data product from CRM and billing data."
    )
    assert result.fail_reason is None, result.fail_reason
    assert not result.failed
    assert not result.parked
    assert result.workflow_states == [phase.value for phase in LEGAL_INTERVIEW_PHASES]
    assert result.parse_ok
    assert result.compile_ok
    assert result.load_ok
    assert result.execute_ok
    assert result.tests_ok
    assert result.quality is not None
    assert result.quality.passed
    assert result.twin_snapshot is not None
    assert result.estate_context_sha256
    assert result.generated is not None
    assert set(REQUIRED_DEMO_MODELS).issubset(set(result.generated.model_names))
    assert result.extra.get("intent_ids")
    assert result.extra.get("evidence_ref_ids")
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, result.workflow_id)
        assert workflow is not None
        assert workflow.state == WorkflowState.VALIDATION.value
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
