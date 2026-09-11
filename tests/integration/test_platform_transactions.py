from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.helpers import SeededTask, SeedInput, seed_task

from aide.capabilities.registry import CapabilityRegistry
from aide.capabilities.spec import (
    CapabilitySpec,
    ConnectorRequirement,
    RetryPolicy,
)
from aide.connectors.base.reconcile import EffectFound, Unknown
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
from aide.domain.states import AttemptOutcome, TaskState, WorkflowState
from aide.orchestration.cancellation import (
    begin_cancellation,
    complete_cancellation,
    park_unresolved_and_cancel,
    request_cancellation,
    run_cancellation_io,
)
from aide.orchestration.compatibility import evaluate_pinned_contract
from aide.orchestration.materialization import advisory_lock_key
from aide.orchestration.recovery import apply_reconcile_result
from aide.orchestration.worker import (
    RecoveryClaim,
    acquire_recovery,
    claim_task,
    finalize_success,
    mark_dispatched,
)
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
    UnresolvedEffectModel,
    WorkflowModel,
)


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


async def _seed_parked_ambiguous_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[SeededTask, UUID, str]:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        worker_claim = await claim_task(
            session,
            owner="worker",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert worker_claim is not None
        await mark_dispatched(session, worker_claim)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        operation_key = task.operation_idempotency_key
    async with session_factory() as session, session.begin():
        recovery = await acquire_recovery(
            session,
            task_id=seeded.task_id,
            recovery_owner="ordinary-reconciler",
            now=now + timedelta(seconds=1),
            lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
            expected_owner=worker_claim.owner,
            expected_epoch=worker_claim.claim_epoch,
            expected_attempt_id=worker_claim.attempt_id,
        )
        assert recovery is not None
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=recovery,
            result=Unknown(reason="provider history unavailable"),
            now=now + timedelta(seconds=2),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=30),
        )
        assert state is TaskState.PARKED
    return seeded, worker_claim.attempt_id, operation_key


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

    async def connector_io(_: RecoveryClaim) -> bool:
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
async def test_recovery_claim_from_before_cancellation_cannot_apply_result(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        worker_claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=30)
        )
        assert worker_claim is not None
        await mark_dispatched(session, worker_claim)
    async with session_factory() as session, session.begin():
        stale_recovery = await acquire_recovery(
            session,
            task_id=seeded.task_id,
            recovery_owner="pre-cancel-reconciler",
            now=now + timedelta(seconds=1),
            lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
            expected_owner=worker_claim.owner,
            expected_epoch=worker_claim.claim_epoch,
            expected_attempt_id=worker_claim.attempt_id,
        )
        assert stale_recovery is not None
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        cancellation_epoch = await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="fence existing reconciliation",
            now=now + timedelta(seconds=2),
        )
        assert cancellation_epoch > stale_recovery.cancellation_epoch

    with pytest.raises(RuntimeError, match="stale recovery result"):
        async with session_factory() as session, session.begin():
            await apply_reconcile_result(
                session,
                claim=stale_recovery,
                result=EffectFound(output={"late": True}),
                now=now + timedelta(seconds=3),
                max_reconcile_checks=3,
                recovery_lease_duration=timedelta(seconds=30),
            )
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        assert task.outputs is None
        assert task.status == TaskState.RECONCILING.value


@pytest.mark.asyncio
async def test_cancellation_replaces_reconciling_ownership_and_adopts_current_result(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        worker_claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=30)
        )
        assert worker_claim is not None
        await mark_dispatched(session, worker_claim)
    async with session_factory() as session, session.begin():
        old_recovery = await acquire_recovery(
            session,
            task_id=seeded.task_id,
            recovery_owner="ordinary-reconciler",
            now=now + timedelta(seconds=1),
            lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
            expected_owner=worker_claim.owner,
            expected_epoch=worker_claim.claim_epoch,
            expected_attempt_id=worker_claim.attempt_id,
        )
        assert old_recovery is not None
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="replace recovery owner",
            now=now + timedelta(seconds=2),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=3),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    assert len(ownership.recovery_claims) == 1
    current_recovery = ownership.recovery_claims[0]
    assert current_recovery.attempt_id == old_recovery.attempt_id
    assert current_recovery.claim_epoch > old_recovery.claim_epoch
    assert current_recovery.cancellation_epoch == ownership.cancellation_epoch

    with pytest.raises(RuntimeError, match="stale recovery result"):
        async with session_factory() as session, session.begin():
            await apply_reconcile_result(
                session,
                claim=old_recovery,
                result=EffectFound(output={"owner": "stale"}),
                now=now + timedelta(seconds=4),
                max_reconcile_checks=3,
                recovery_lease_duration=timedelta(seconds=30),
            )
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=current_recovery,
            result=EffectFound(output={"owner": "cancellation-coordinator"}),
            now=now + timedelta(seconds=5),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=30),
        )
        assert state is TaskState.SUCCEEDED
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        assert task.outputs == {"owner": "cancellation-coordinator"}


@pytest.mark.asyncio
async def test_terminal_cancellation_rejects_hidden_active_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        worker_claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=30)
        )
        assert worker_claim is not None
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="test complete coverage",
            now=now + timedelta(seconds=1),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=2),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    assert len(ownership.recovery_claims) == 1
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        terminal_version = workflow.version

    with pytest.raises(ValueError, match="exactly cover every active task"):
        async with session_factory() as session, session.begin():
            await park_unresolved_and_cancel(
                session,
                workflow_id=seeded.workflow_id,
                expected_workflow_version=terminal_version,
                principal_id=uuid4(),
                unresolved=(),
                required_follow_up="verify external state",
                now=now + timedelta(seconds=3),
            )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        unresolved_count = await session.scalar(
            select(func.count())
            .select_from(UnresolvedEffectModel)
            .where(UnresolvedEffectModel.workflow_id == seeded.workflow_id)
        )
        assert workflow is not None and task is not None
        assert workflow.state == WorkflowState.CANCELLING.value
        assert task.status == TaskState.RECONCILING.value
        assert unresolved_count == 0


@pytest.mark.asyncio
async def test_unresolved_cancellation_evidence_and_terminal_state_are_atomic(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    principal_id = uuid4()
    async with session_factory() as session, session.begin():
        worker_claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=30)
        )
        assert worker_claim is not None
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=principal_id,
            reason="park unresolved effect",
            now=now + timedelta(seconds=1),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=2),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    claim = ownership.recovery_claims[0]
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        terminal_version = workflow.version

    with pytest.raises(RuntimeError, match="rollback terminal cancellation"):
        async with session_factory() as session, session.begin():
            await park_unresolved_and_cancel(
                session,
                workflow_id=seeded.workflow_id,
                expected_workflow_version=terminal_version,
                principal_id=principal_id,
                unresolved=((claim, {"locator": "effect"}, {"status": "unknown"}),),
                required_follow_up="verify external state",
                now=now + timedelta(seconds=3),
            )
            raise RuntimeError("rollback terminal cancellation")
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        unresolved_count = await session.scalar(
            select(func.count())
            .select_from(UnresolvedEffectModel)
            .where(UnresolvedEffectModel.workflow_id == seeded.workflow_id)
        )
        cancel_event_count = await session.scalar(
            select(func.count())
            .select_from(AuditEventModel)
            .where(
                AuditEventModel.workflow_id == seeded.workflow_id,
                AuditEventModel.event_type == "WORKFLOW_CANCELLED_WITH_UNRESOLVED_EFFECTS",
            )
        )
        assert workflow is not None and task is not None
        assert workflow.state == WorkflowState.CANCELLING.value
        assert task.status == TaskState.RECONCILING.value
        assert task.recovery_owner == claim.owner
        assert unresolved_count == 0
        assert cancel_event_count == 0

    async with session_factory() as session, session.begin():
        await park_unresolved_and_cancel(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=terminal_version,
            principal_id=principal_id,
            unresolved=((claim, {"locator": "effect"}, {"status": "unknown"}),),
            required_follow_up="verify external state",
            now=now + timedelta(seconds=4),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        unresolved_count = await session.scalar(
            select(func.count())
            .select_from(UnresolvedEffectModel)
            .where(UnresolvedEffectModel.workflow_id == seeded.workflow_id)
        )
        cancel_event = await session.scalar(
            select(AuditEventModel).where(
                AuditEventModel.workflow_id == seeded.workflow_id,
                AuditEventModel.event_type == "WORKFLOW_CANCELLED_WITH_UNRESOLVED_EFFECTS",
            )
        )
        assert workflow is not None and task is not None
        assert workflow.state == WorkflowState.CANCELLED.value
        assert task.status == TaskState.CANCELLED.value
        assert task.active_attempt_id is None
        assert task.recovery_owner is None
        assert unresolved_count == 1
        assert cancel_event is not None


@pytest.mark.asyncio
async def test_terminal_cancellation_is_atomic_and_has_quiescent_normal_path(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="normal cancellation",
            now=now,
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=1),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
        assert ownership.recovery_claims == ()
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        completion_version = workflow.version
    async with session_factory() as session, session.begin():
        await complete_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=completion_version,
            now=now + timedelta(seconds=2),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        event = await session.scalar(
            select(AuditEventModel).where(
                AuditEventModel.workflow_id == seeded.workflow_id,
                AuditEventModel.event_type == "WORKFLOW_CANCELLED",
            )
        )
        assert workflow is not None and task is not None
        assert workflow.state == WorkflowState.CANCELLED.value
        assert task.status == TaskState.CANCELLED.value
        assert task.lease_owner is None
        assert task.recovery_owner is None
        assert event is not None


@pytest.mark.asyncio
async def test_parked_ambiguous_task_reconciles_during_cancellation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded, historical_attempt_id, operation_key = await _seed_parked_ambiguous_task(
        session_factory
    )
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="cancel parked ambiguous effect",
            now=now + timedelta(seconds=3),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=4),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    assert len(ownership.recovery_claims) == 1
    cancellation_claim = ownership.recovery_claims[0]
    assert cancellation_claim.attempt_id == historical_attempt_id

    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=cancellation_claim,
            result=EffectFound(output={"reconciled": True}, external_ref="effect-1"),
            now=now + timedelta(seconds=5),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=30),
        )
        assert state is TaskState.SUCCEEDED
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        completion_version = workflow.version
    async with session_factory() as session, session.begin():
        await complete_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=completion_version,
            now=now + timedelta(seconds=6),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        attempt = await session.get(TaskAttemptModel, historical_attempt_id)
        attempt_count = await session.scalar(
            select(func.count())
            .select_from(TaskAttemptModel)
            .where(TaskAttemptModel.task_id == seeded.task_id)
        )
        assert workflow is not None and task is not None and attempt is not None
        assert workflow.state == WorkflowState.CANCELLED.value
        assert task.status == TaskState.SUCCEEDED.value
        assert task.operation_idempotency_key == operation_key
        assert task.outputs == {"reconciled": True}
        assert attempt.outcome == AttemptOutcome.AMBIGUOUS.value
        assert attempt.result is None
        assert attempt.finished_at == now + timedelta(seconds=2)
        assert attempt_count == 1


@pytest.mark.asyncio
async def test_parked_ambiguous_task_is_durably_recorded_before_cancelled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded, historical_attempt_id, operation_key = await _seed_parked_ambiguous_task(
        session_factory
    )
    now = datetime(2026, 9, 11, 18, 0, 0)
    principal_id = uuid4()
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=principal_id,
            reason="durably park ambiguous effect",
            now=now + timedelta(seconds=3),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=4),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    cancellation_claim = ownership.recovery_claims[0]
    assert cancellation_claim.attempt_id == historical_attempt_id
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        terminal_version = workflow.version
    recovery_context = {
        "operation_idempotency_key": operation_key,
        "attempt_id": str(historical_attempt_id),
    }
    async with session_factory() as session, session.begin():
        await park_unresolved_and_cancel(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=terminal_version,
            principal_id=principal_id,
            unresolved=(
                (
                    cancellation_claim,
                    recovery_context,
                    {"status": "still ambiguous"},
                ),
            ),
            required_follow_up="verify external state",
            now=now + timedelta(seconds=5),
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        attempt = await session.get(TaskAttemptModel, historical_attempt_id)
        unresolved = await session.scalar(
            select(UnresolvedEffectModel).where(
                UnresolvedEffectModel.workflow_id == seeded.workflow_id
            )
        )
        assert (
            workflow is not None
            and task is not None
            and attempt is not None
            and unresolved is not None
        )
        assert workflow.state == WorkflowState.CANCELLED.value
        assert task.status == TaskState.CANCELLED.value
        assert attempt.outcome == AttemptOutcome.AMBIGUOUS.value
        assert attempt.finished_at == now + timedelta(seconds=2)
        assert unresolved.attempt_id == historical_attempt_id
        assert unresolved.operation_idempotency_key == operation_key
        assert unresolved.recovery_context == recovery_context


@pytest.mark.asyncio
async def test_ordinary_recovery_cannot_replace_cancellation_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = datetime(2026, 9, 11, 18, 0, 0)
    async with session_factory() as session, session.begin():
        worker_claim = await claim_task(
            session,
            owner="worker",
            now=now,
            lease_duration=timedelta(seconds=30),
        )
        assert worker_claim is not None
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        expected_version = workflow.version
    async with session_factory() as session, session.begin():
        await request_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=expected_version,
            actor_principal_id=uuid4(),
            reason="protect cancellation ownership",
            now=now + timedelta(seconds=1),
        )
    async with session_factory() as session, session.begin():
        assert (
            await acquire_recovery(
                session,
                task_id=seeded.task_id,
                recovery_owner="ordinary-reconciler",
                now=now + timedelta(seconds=2),
                lease_duration=timedelta(seconds=30),
                reconcile_deadline=now + timedelta(minutes=2),
                expected_owner=worker_claim.owner,
                expected_epoch=worker_claim.claim_epoch,
                expected_attempt_id=worker_claim.attempt_id,
            )
            is None
        )
    async with session_factory() as session:
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert workflow is not None
        cancellation_version = workflow.version
    async with session_factory() as session, session.begin():
        ownership = await begin_cancellation(
            session,
            workflow_id=seeded.workflow_id,
            expected_workflow_version=cancellation_version,
            owner="cancellation-coordinator",
            now=now + timedelta(seconds=3),
            recovery_lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=2),
        )
    cancellation_claim = ownership.recovery_claims[0]
    async with session_factory() as session, session.begin():
        assert (
            await acquire_recovery(
                session,
                task_id=seeded.task_id,
                recovery_owner="ordinary-reconciler",
                now=now + timedelta(seconds=4),
                lease_duration=timedelta(seconds=30),
                reconcile_deadline=now + timedelta(minutes=2),
                expected_owner=cancellation_claim.owner,
                expected_epoch=cancellation_claim.claim_epoch,
                expected_attempt_id=cancellation_claim.attempt_id,
            )
            is None
        )
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        assert task.status == TaskState.RECONCILING.value
        assert task.recovery_owner == cancellation_claim.owner
        assert task.claim_epoch == cancellation_claim.claim_epoch
        assert task.active_attempt_id == cancellation_claim.attempt_id


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

    async def append(event_type: str) -> None:
        async with session_factory() as session, session.begin():
            await append_audit_event(
                session,
                workflow_id=seeded.workflow_id,
                event_type=event_type,
                payload={},
            )

    await asyncio.gather(append("ONE"), append("TWO"), append("THREE"))
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
