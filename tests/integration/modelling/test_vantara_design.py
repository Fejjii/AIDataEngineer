from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.domain.states import WorkflowState
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.modelling.service import run_design_phase
from aide.modelling.vantara import (
    vantara_demo_requirement,
    vantara_modelling_context,
    vantara_required_models,
)
from aide.orchestration.materialization import create_phase_occurrence
from aide.orchestration.phases.design import (
    DESIGN_EXIT_CRITERIA,
    build_design_plan,
    build_design_templates,
)
from aide.persistence.models import PhaseRunModel, TaskTemplateModel
from aide.persistence.repositories import ContractSnapshotRepository, WorkflowRepository
from aide.profiling.engine import profile_selected_assets
from aide.profiling.fixtures import demo_selected_assets
from aide.profiling.offline import open_offline_vantara


@pytest.mark.asyncio
async def test_offline_vantara_profiling_feeds_expected_design() -> None:
    connector = open_offline_vantara("v2")
    try:
        selected = demo_selected_assets()
        run = await profile_selected_assets(connector, selected, fixture_version="v2")
        result = run_design_phase(
            vantara_demo_requirement(),
            run,
            selected,
            context=vantara_modelling_context(),
        )
    finally:
        await connector.close()
    decision = result.architecture_decision
    assert decision.layering.rule == "L1"
    assert decision.integration_layer.rule == "V3"
    assert decision.presentation.rule == "P1"
    assert decision.approval_required is False
    assert decision.signals.identifier_alignment == "PARTIAL"
    assert not any(item.blocking for item in decision.open_questions)
    expected = (
        "L1",
        "V3",
        "P1",
        "F1",
        "F2",
        "F4",
        "D1",
        "D6",
        "D7",
        "D8",
        "M1",
        "M2",
        "M3",
        "M6",
    )
    for rule in expected:
        assert rule in decision.rule_ids
    assert result.validation.passed, tuple(
        (item.code, item.message) for item in result.validation.violations
    )
    assert result.model_design is not None
    names = {item.name for item in result.model_design.models}
    for required in vantara_required_models():
        assert required in names
    assert result.recommended_next_state is WorkflowState.PLANNING


@pytest.mark.asyncio
async def test_design_phase_templates_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    templates = build_design_templates()
    plan = build_design_plan()
    async with session_factory() as session, session.begin():
        workflow = await WorkflowRepository(session).add(state=WorkflowState.PLANNING)
        snapshot = ContractSnapshot(
            snapshot_id=uuid4(),
            capability_contracts=(
                CapabilityContractRef(
                    capability_id="propose_model_design",
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
            ),
            connector_versions={},
        )
        await ContractSnapshotRepository(session).add(
            workflow_id=workflow.workflow_id, snapshot=snapshot
        )
        phase_run_id = uuid4()
        phase = await create_phase_occurrence(
            session,
            workflow_id=workflow.workflow_id,
            phase_run_id=phase_run_id,
            phase=WorkflowState.DESIGN,
            expected_workflow_version=workflow.version,
            expected_generation=1,
            contract_snapshot_id=snapshot.snapshot_id,
            templates=templates,
            phase_exit_criteria=plan.phase_exit_criteria,
        )
        stored = (
            await session.scalars(
                select(TaskTemplateModel)
                .where(TaskTemplateModel.phase_run_id == phase.phase_run_id)
                .order_by(TaskTemplateModel.local_id)
            )
        ).all()
        assert [item.local_id for item in stored] == sorted(item.local_id for item in stored)
        assert stored[0].capability_id == "propose_model_design"
        assert list(phase.phase_exit_criteria) == list(DESIGN_EXIT_CRITERIA)
    async with session_factory() as session:
        persisted = await session.get(PhaseRunModel, phase_run_id)
        assert persisted is not None
        assert persisted.phase == WorkflowState.DESIGN.value
