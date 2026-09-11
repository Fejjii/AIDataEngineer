from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.exc import DBAPIError

from aide.capabilities.registry import CapabilityRegistry
from aide.capabilities.spec import (
    CapabilitySpec,
    ConnectorRequirement,
    RetryPolicy,
)
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import (
    CapabilityImplementation,
    ConnectorKind,
    ConnectorSpec,
    IdentityClass,
    ObjectAllowList,
)
from aide.domain.costs import BudgetScope, CostUnit
from aide.domain.effects import EffectSemantics
from aide.domain.enums import ApprovalRule, RiskLevel, TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import TaskState, WorkflowState
from aide.orchestration.cancellation import (
    begin_cancellation,
    request_cancellation,
    run_cancellation_io,
)
from aide.orchestration.compatibility import evaluate_pinned_contract
from aide.orchestration.materialization import advisory_lock_key
from aide.orchestration.worker import claim_task, mark_dispatched
from aide.persistence.audit import append_audit_event
from aide.persistence.budget import BudgetExceededError, BudgetLedger
from aide.persistence.models import (
    AuditEventModel,
    BudgetEntryModel,
    BudgetLedgerModel,
    MaterializedTaskModel,
    PhaseRunModel,
    TaskAttemptModel,
    TaskTemplateModel,
    WorkflowModel,
)
from tests.integration.helpers import SeedInput, seed_task


class SeedOutput(BaseModel):
    applied: bool


def _runtime_registries(*, available: bool) -> tuple[CapabilityRegistry, ConnectorRegistry]:
    capabilities = CapabilityRegistry()
    connectors = ConnectorRegistry()
    if not available:
        return capabilities, connectors
    capabilities.register(
        CapabilitySpec(
            id="fake_side_effect",
            version=1,
            kind="deterministic",
            purpose="Test a deterministic fake effect",
            input_schema=SeedInput,
            output_schema=SeedOutput,
            input_schema_version=1,
            output_schema_version=1,
            required_permission=PermissionLevel.DEVELOPMENT_WRITE,
            risk=RiskLevel.MEDIUM,
            approval=ApprovalRule.NEVER,
            timeout_seconds=30,
            retry=RetryPolicy(max_attempts=2),
            failure_classes=frozenset(),
            connector_requirement=ConnectorRequirement(
                mode="REQUIRED", kinds=frozenset({ConnectorKind.DATABASE.value})
            ),
            effect_semantics=EffectSemantics.EXTERNALLY_DEDUPLICATED,
            cost_class="free",
        )
    )
    connectors.register(
        ConnectorSpec(
            connector_id="fake",
            kind=ConnectorKind.DATABASE,
            vendor="fake",
            version="1.0",
            target_environment=TargetEnv.DEV,
            identity_class=IdentityClass.DEVELOPMENT,
            implementations=frozenset(
                {
                    CapabilityImplementation(
                        capability_id="fake_side_effect",
                        supported_contract_versions=frozenset({1}),
                        input_schema_versions=frozenset({1}),
                        output_schema_versions=frozenset({1}),
                    )
                }
            ),
            allowed_permissions=frozenset({PermissionLevel.DEVELOPMENT_WRITE}),
            allow_list=ObjectAllowList(),
            is_fake=True,
        ),
        required_permissions={
            "fake_side_effect": PermissionLevel.DEVELOPMENT_WRITE,
        },
    )
    return capabilities, connectors


@pytest.mark.asyncio
async def test_cancellation_ownership_is_serialized_and_io_runs_after_unlock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=30)
        )
        assert claim is not None
        await mark_dispatched(session, claim)
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="operator request",
            now=now + timedelta(seconds=1),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancel_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancel_version,
            owner="canceller",
            now=now + timedelta(seconds=2),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    assert len(ownership.recovery_claims) == 1

    async def connector_io(_: object) -> bool:
        async with session_factory() as session, session.begin():
            acquired = await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"),
                {"key": advisory_lock_key(seeded.workflow_id)},
            )
            return bool(acquired)

    assert await run_cancellation_io(ownership, connector_io) == (True,)
    async with session_factory() as session:
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(TaskAttemptModel)
            .where(TaskAttemptModel.task_id == seeded.task_id)
        )
        events = (
            await session.scalars(
                select(AuditEventModel.event_type).where(
                    AuditEventModel.workflow_id == seeded.workflow_id
                )
            )
        ).all()
        assert attempt_count == 1
        assert "CANCELLATION_OWNERSHIP_RECORDED" in events


@pytest.mark.asyncio
async def test_cancellation_epoch_fences_prior_worker_result(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from aide.orchestration.worker import finalize_success

    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=30)
        )
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert claim is not None and workflow is not None
        version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=version,
            actor_principal_id=uuid4(),
            reason="stop",
            now=now + timedelta(seconds=1),
        )
    async with session_factory() as session, session.begin():
        assert not await finalize_success(
            session, claim=claim, output={"late": True}, now=now + timedelta(seconds=2)
        )


@pytest.mark.asyncio
async def test_audit_mutation_and_event_roll_back_atomically(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session:
        initial_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.workflow_id == seeded.workflow_id)
        )
    with pytest.raises(RuntimeError, match="rollback"):
        async with session_factory() as session, session.begin():
            task = await session.get(MaterializedTaskModel, seeded.task_id)
            assert task is not None
            task.status = TaskState.FAILED.value
            await append_audit_event(
                session,
                workflow_id=seeded.workflow_id,
                task_id=seeded.task_id,
                event_type="ROLLBACK_TEST",
                payload={},
            )
            raise RuntimeError("rollback")
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        final_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(AuditEventModel.workflow_id == seeded.workflow_id)
        )
        assert task is not None
        assert task.status == TaskState.READY.value
        assert final_count == initial_count


@pytest.mark.asyncio
async def test_audit_sequence_is_monotonic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        await append_audit_event(
            session,
            workflow_id=seeded.workflow_id,
            event_type="ONE",
            payload={},
        )
        await append_audit_event(
            session,
            workflow_id=seeded.workflow_id,
            event_type="TWO",
            payload={},
        )
    async with session_factory() as session:
        sequences = list(
            (
                await session.scalars(
                    select(AuditEventModel.sequence)
                    .where(AuditEventModel.workflow_id == seeded.workflow_id)
                    .order_by(AuditEventModel.sequence)
                )
            ).all()
        )
        assert sequences == list(range(1, len(sequences) + 1))


@pytest.mark.asyncio
async def test_concurrent_budget_reservations_respect_cap(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        await BudgetLedger(session).create(
            workflow_id=seeded.workflow_id,
            scope=BudgetScope.WORKFLOW_LLM,
            unit=CostUnit.USD,
            authorized_cap=Decimal("10"),
        )

    async def reserve() -> object:
        try:
            async with session_factory() as session, session.begin():
                return await BudgetLedger(session).reserve(
                    workflow_id=seeded.workflow_id,
                    scope=BudgetScope.WORKFLOW_LLM,
                    unit=CostUnit.USD,
                    worst_case=Decimal("7"),
                    evidence={"call": "test"},
                )
        except BudgetExceededError as exc:
            return exc

    results = await asyncio.gather(reserve(), reserve())
    assert sum(isinstance(result, BudgetExceededError) for result in results) == 1
    async with session_factory() as session:
        ledger = await session.scalar(
            select(BudgetLedgerModel).where(BudgetLedgerModel.workflow_id == seeded.workflow_id)
        )
        entries = await session.scalar(select(func.count()).select_from(BudgetEntryModel))
        assert ledger is not None
        assert ledger.reserved_amount == Decimal("7")
        assert entries == 1


@pytest.mark.asyncio
async def test_budget_settlement_reconstructs_remaining_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    async with session_factory() as session, session.begin():
        ledger = BudgetLedger(session)
        await ledger.create(
            workflow_id=seeded.workflow_id,
            scope=BudgetScope.WORKFLOW_LLM,
            unit=CostUnit.USD,
            authorized_cap=Decimal("10"),
        )
        reservation = await ledger.reserve(
            workflow_id=seeded.workflow_id,
            scope=BudgetScope.WORKFLOW_LLM,
            unit=CostUnit.USD,
            worst_case=Decimal("6"),
            evidence={"estimate": "worst-case"},
        )
        settlement = await ledger.settle(
            workflow_id=seeded.workflow_id,
            scope=BudgetScope.WORKFLOW_LLM,
            unit=CostUnit.USD,
            reservation_id=reservation.reservation_id,
            actual_amount=Decimal("4"),
            evidence={"provider_usage": "validated"},
        )
        assert settlement.released_amount == Decimal("2")
        assert settlement.remaining_budget == Decimal("6")


@pytest.mark.asyncio
async def test_contract_version_unavailable_parks_and_resume_reevaluates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    unavailable_capabilities, unavailable_connectors = _runtime_registries(available=False)
    async with session_factory() as session, session.begin():
        assert not await evaluate_pinned_contract(
            session,
            task_id=seeded.task_id,
            capabilities=unavailable_capabilities,
            connectors=unavailable_connectors,
        )
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        phase = await session.get(PhaseRunModel, seeded.phase_run_id)
        assert task is not None and workflow is not None and phase is not None
        assert task.status == TaskState.PARKED.value
        assert workflow.state == WorkflowState.BLOCKED.value
        assert phase.contract_snapshot_id == seeded.snapshot_id
    capabilities, connectors = _runtime_registries(available=True)
    async with session_factory() as session, session.begin():
        assert await evaluate_pinned_contract(
            session,
            task_id=seeded.task_id,
            capabilities=capabilities,
            connectors=connectors,
        )
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        assert task.status == TaskState.READY.value


@pytest.mark.asyncio
async def test_database_trigger_enforces_immutable_task_template(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    with pytest.raises(DBAPIError):
        async with session_factory() as session, session.begin():
            template = await session.scalar(
                select(TaskTemplateModel).where(
                    TaskTemplateModel.phase_run_id == seeded.phase_run_id
                )
            )
            assert template is not None
            template.timeout_seconds = 999
