from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.connectors.base.context import (
    AttemptRecoveryRef,
    CallContext,
    RecoveryContext,
)
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.fake.side_effects import (
    AmbiguousSideEffectError,
    FakeSideEffectConnector,
    FaultMode,
)
from aide.domain.enums import TargetEnv
from aide.domain.states import TaskState
from aide.domain.versions import CapabilityContractRef
from aide.orchestration.recovery import apply_reconcile_result
from aide.orchestration.worker import (
    RecoveryClaim,
    TaskClaim,
    acquire_recovery,
    claim_task,
    mark_dispatched,
)
from aide.persistence.models import MaterializedTaskModel, RecoveryEventModel
from tests.integration.helpers import seed_task


def now() -> datetime:
    return datetime(2026, 9, 11, 18, 0, 0)


async def _claim_and_recover(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    max_attempts: int = 2,
) -> tuple[TaskClaim, RecoveryClaim, MaterializedTaskModel]:
    seeded = await seed_task(session_factory, max_attempts=max_attempts)
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now(), lease_duration=timedelta(seconds=10)
        )
        assert claim is not None
        await mark_dispatched(session, claim)
    async with session_factory() as session, session.begin():
        recovery = await acquire_recovery(
            session,
            task_id=seeded.task_id,
            recovery_owner="reconciler",
            now=now() + timedelta(seconds=1),
            lease_duration=timedelta(seconds=10),
            reconcile_deadline=now() + timedelta(minutes=1),
            expected_owner=claim.owner,
            expected_epoch=claim.claim_epoch,
            expected_attempt_id=claim.attempt_id,
        )
        assert recovery is not None
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        session.expunge(task)
    return claim, recovery, task


@pytest.mark.parametrize("fault", list(FaultMode))
@pytest.mark.asyncio
async def test_ambiguous_failure_reconciles_before_any_retry(
    session_factory: async_sessionmaker[AsyncSession],
    fault: FaultMode,
) -> None:
    seeded = await seed_task(session_factory)
    connector = FakeSideEffectConnector()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now(), lease_duration=timedelta(seconds=10)
        )
        assert claim is not None
        await mark_dispatched(session, claim)
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        operation_key = task.operation_idempotency_key
        connector.fail_next(operation_key, fault, effect_applied=True)
        call_context = CallContext(
            workflow_id=seeded.workflow_id,
            phase_run_id=seeded.phase_run_id,
            task_id=seeded.task_id,
            operation_idempotency_key=operation_key,
            resolved_input_digest=task.resolved_input_digest,
            contract_snapshot_id=seeded.snapshot_id,
            attempt_id=claim.attempt_id,
            attempt_number=claim.attempt_number,
            claim_epoch=claim.claim_epoch,
            cancellation_epoch=claim.cancellation_epoch,
            deadline=now() + timedelta(seconds=30),
            external_correlation="fake",
        )
    with pytest.raises(AmbiguousSideEffectError):
        await connector.execute({"value": "payload"}, call_context)
    async with session_factory() as session, session.begin():
        recovery = await acquire_recovery(
            session,
            task_id=seeded.task_id,
            recovery_owner="reconciler",
            now=now() + timedelta(seconds=1),
            lease_duration=timedelta(seconds=10),
            reconcile_deadline=now() + timedelta(minutes=1),
            expected_owner=claim.owner,
            expected_epoch=claim.claim_epoch,
            expected_attempt_id=claim.attempt_id,
        )
        assert recovery is not None
    recovery_context = RecoveryContext(
        workflow_id=seeded.workflow_id,
        phase_run_id=seeded.phase_run_id,
        task_id=seeded.task_id,
        operation_idempotency_key=operation_key,
        resolved_input_digest=call_context.resolved_input_digest,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id="fake_side_effect",
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="fake",
        connector_version="1.0",
        target_environment=TargetEnv.DEV,
        attempts=(
            AttemptRecoveryRef(
                attempt_id=claim.attempt_id,
                attempt_number=claim.attempt_number,
            ),
        ),
        reconcile_deadline=now() + timedelta(minutes=1),
    )
    result = await connector.reconcile(recovery_context)
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=recovery,
            result=result,
            now=now() + timedelta(seconds=2),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=10),
        )
    assert state is TaskState.SUCCEEDED
    assert connector.calls == [("execute", operation_key), ("reconcile", operation_key)]
    assert connector.effect_counts[operation_key] == 1


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (EffectFound(output={"ok": True}), TaskState.SUCCEEDED),
        (NoEffect(evidence="not found"), TaskState.RETRY_WAIT),
        (
            InProgress(external_ref="running", retry_after_seconds=1),
            TaskState.RECONCILING,
        ),
        (Unknown(reason="history unavailable"), TaskState.PARKED),
    ],
)
@pytest.mark.asyncio
async def test_every_reconcile_result_branch(
    session_factory: async_sessionmaker[AsyncSession],
    result: EffectFound | NoEffect | InProgress | Unknown,
    expected: TaskState,
) -> None:
    _, recovery_value, _ = await _claim_and_recover(session_factory)
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=recovery_value,
            result=result,
            now=now() + timedelta(seconds=2),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=10),
        )
        assert state is expected


@pytest.mark.asyncio
async def test_no_effect_with_exhausted_attempts_becomes_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, recovery_value, task = await _claim_and_recover(session_factory, max_attempts=1)
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=recovery_value,
            result=NoEffect(evidence="authoritative absence"),
            now=now() + timedelta(seconds=2),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=10),
        )
        assert state is TaskState.FAILED
    async with session_factory() as session:
        persisted = await session.get(MaterializedTaskModel, task.task_id)
        assert persisted is not None
        assert persisted.status == TaskState.FAILED.value
        assert persisted.disposition_reason == "NO_EFFECT_ATTEMPTS_EXHAUSTED"


@pytest.mark.asyncio
async def test_in_progress_is_bounded_and_never_degrades_to_no_effect(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, recovery_value, task = await _claim_and_recover(session_factory)
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=recovery_value,
            result=InProgress(external_ref="running", retry_after_seconds=1),
            now=now() + timedelta(seconds=2),
            max_reconcile_checks=1,
            recovery_lease_duration=timedelta(seconds=10),
        )
        assert state is TaskState.PARKED
    async with session_factory() as session:
        persisted = await session.get(MaterializedTaskModel, task.task_id)
        assert persisted is not None
        assert persisted.disposition_reason == "IN_PROGRESS_EXHAUSTED"
        count = await session.scalar(
            select(func.count())
            .select_from(RecoveryEventModel)
            .where(RecoveryEventModel.task_id == task.task_id)
        )
        assert count == 1
