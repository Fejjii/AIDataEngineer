from __future__ import annotations

from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.domain.enums import RiskLevel, TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.orchestration.materialization import create_phase_occurrence, persist_materialized_task
from aide.orchestration.phases.profiling import build_profiling_plan, build_profiling_templates
from aide.persistence.models import PhaseRunModel, TaskTemplateModel
from aide.persistence.repositories import ContractSnapshotRepository, WorkflowRepository
from aide.profiling.budgets import TINY_OFFLINE_BUDGET
from aide.profiling.engine import profile_selected_assets
from aide.profiling.fixtures import demo_selected_assets
from aide.profiling.offline import open_offline_vantara


@pytest.mark.asyncio
async def test_offline_vantara_tiny_completes_under_60s() -> None:
    connector = open_offline_vantara("v2")
    try:
        selected = demo_selected_assets()
        started = perf_counter()
        result = await profile_selected_assets(
            connector, selected, fixture_version="v2", budget=TINY_OFFLINE_BUDGET
        )
        duration = perf_counter() - started
        assert duration < 60
        assert len(result.profiles) == 10
        assert result.summary.budget.elapsed_seconds < 60
        assert result.duration_seconds < 60
        p1 = next(item for item in result.summary.facts if item.fact_id == "P1_duplicate_accounts")
        p3 = next(
            item for item in result.summary.facts if item.fact_id == "P3_crm_billing_crosswalk"
        )
        p10 = next(item for item in result.summary.facts if item.fact_id == "P10_payment_grain")
        assert isinstance(p1.value, float) and p1.value < 1
        assert isinstance(p3.value, float) and p3.value < 1
        assert isinstance(p10.value, float) and p10.value < 1
        assert result.masking.samples_masked is True
        assert result.summary.budget.queries <= TINY_OFFLINE_BUDGET.max_queries
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_profiling_phase_completes_with_sorted_templates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    selected = demo_selected_assets()
    templates = build_profiling_templates(selected)
    plan = build_profiling_plan(selected)
    async with session_factory() as session, session.begin():
        workflow = await WorkflowRepository(session).add(state=WorkflowState.PLANNING)
        snapshot = ContractSnapshot(
            snapshot_id=uuid4(),
            capability_contracts=(
                CapabilityContractRef(
                    capability_id="profile_dataset",
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
                CapabilityContractRef(
                    capability_id="infer_relationships",
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
                CapabilityContractRef(
                    capability_id="sample_dataset",
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
            ),
            connector_versions={"snowflake_ro": "1.0.0"},
        )
        await ContractSnapshotRepository(session).add(
            workflow_id=workflow.workflow_id, snapshot=snapshot
        )
        phase_run_id = uuid4()
        phase = await create_phase_occurrence(
            session,
            workflow_id=workflow.workflow_id,
            phase_run_id=phase_run_id,
            phase=WorkflowState.PROFILING,
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
        local_ids = [item.local_id for item in stored]
        assert local_ids == sorted(local_ids)
        assert any(item.capability_id == "infer_relationships" for item in stored)
        assert len(stored) == len(templates)
        first_profile = next(item for item in stored if item.capability_id == "profile_dataset")
        from aide.domain.tasks import TaskTemplate

        template = TaskTemplate(
            template_id=first_profile.template_id,
            phase_run_id=phase_run_id,
            local_id=first_profile.local_id,
            capability_id=first_profile.capability_id,
            capability_contract_version=first_profile.capability_contract_version,
            connector_id=first_profile.connector_id,
            depends_on=tuple(first_profile.depends_on),
            unresolved_inputs=first_profile.unresolved_inputs,
            timeout_seconds=first_profile.timeout_seconds,
            max_attempts=first_profile.max_attempts,
        )
        from aide.capabilities.io import ProfileDatasetInput

        await persist_materialized_task(
            session,
            template=template,
            task_id=uuid4(),
            workflow_id=workflow.workflow_id,
            resolved_inputs=first_profile.unresolved_inputs,
            input_schema=ProfileDatasetInput,
            input_schema_version=1,
            output_schema_version=1,
            connector_id="snowflake_ro",
            connector_version="1.0.0",
            target_environment=TargetEnv.DEV,
            required_permission=PermissionLevel.READ,
            risk=RiskLevel.LOW,
        )
    async with session_factory() as session:
        persisted = await session.get(PhaseRunModel, phase_run_id)
        assert persisted is not None
        assert persisted.phase == WorkflowState.PROFILING.value
        assert persisted.phase_exit_criteria == list(plan.phase_exit_criteria)
