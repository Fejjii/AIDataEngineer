from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.helpers import seed_task

from aide.connectors.base.reconcile import NoEffect
from aide.domain.states import TaskState
from aide.orchestration.recovery import apply_reconcile_result
from aide.orchestration.worker import (
    RecoveryClaim,
    acquire_expired_recovery,
    acquire_recovery,
    claim_task,
    finalize_success,
    mark_dispatched,
    renew_heartbeat,
)
from aide.persistence.models import MaterializedTaskModel, TaskAttemptModel


def moment() -> datetime:
    return datetime(2026, 9, 11, 18, 0, 0)


@pytest.mark.asyncio
async def test_two_workers_cannot_finalize_one_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_task(session_factory)
    now = moment()
    async with session_factory() as first, first.begin():
        claim = await claim_task(
            first, owner="worker-1", now=now, lease_duration=timedelta(seconds=30)
        )
    assert claim is not None
    async with session_factory() as second, second.begin():
        assert (
            await claim_task(
                second, owner="worker-2", now=now, lease_duration=timedelta(seconds=30)
            )
            is None
        )
    async with session_factory() as session, session.begin():
        assert await finalize_success(session, claim=claim, output={"ok": True}, now=now)
        assert not await finalize_success(session, claim=claim, output={"ok": False}, now=now)


@pytest.mark.asyncio
async def test_stale_worker_after_recovery_updates_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = moment()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker-1", now=now, lease_duration=timedelta(seconds=1)
        )
        assert claim is not None
        assert await mark_dispatched(session, claim)
    async with session_factory() as session, session.begin():
        recovery = await acquire_expired_recovery(
            session,
            recovery_owner="reaper",
            now=now + timedelta(seconds=2),
            lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=5),
        )
    assert recovery is not None
    async with session_factory() as session, session.begin():
        assert not await finalize_success(
            session,
            claim=claim,
            output={"stale": True},
            now=now + timedelta(seconds=3),
        )
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        assert task is not None
        assert task.outputs is None
        assert task.status == TaskState.RECONCILING.value


@pytest.mark.asyncio
async def test_only_one_reconciler_acquires_recovery_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    now = moment()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=10)
        )
    assert claim is not None

    async def recover(owner: str) -> RecoveryClaim | None:
        async with session_factory() as session, session.begin():
            return await acquire_recovery(
                session,
                task_id=seeded.task_id,
                recovery_owner=owner,
                now=now + timedelta(seconds=1),
                lease_duration=timedelta(seconds=10),
                reconcile_deadline=now + timedelta(minutes=1),
                expected_owner=claim.owner,
                expected_epoch=claim.claim_epoch,
                expected_attempt_id=claim.attempt_id,
            )

    results = await asyncio.gather(recover("r1"), recover("r2"))
    assert sum(result is not None for result in results) == 1


@pytest.mark.asyncio
async def test_heartbeat_renewal_preserves_valid_ownership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_task(session_factory)
    now = moment()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=2)
        )
    assert claim is not None
    async with session_factory() as session, session.begin():
        assert await renew_heartbeat(
            session,
            claim=claim,
            now=now + timedelta(seconds=1),
            lease_duration=timedelta(seconds=10),
        )
    async with session_factory() as session, session.begin():
        recovery = await acquire_expired_recovery(
            session,
            recovery_owner="reaper",
            now=now + timedelta(seconds=3),
            lease_duration=timedelta(seconds=30),
            reconcile_deadline=now + timedelta(minutes=5),
        )
        assert recovery is None
    async with session_factory() as session, session.begin():
        assert await finalize_success(
            session,
            claim=claim,
            output={"ok": True},
            now=now + timedelta(seconds=4),
        )


@pytest.mark.asyncio
async def test_lease_expiration_transfers_ownership_safely(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_task(session_factory, max_attempts=2)
    now = moment()
    async with session_factory() as session, session.begin():
        first = await claim_task(
            session, owner="worker-1", now=now, lease_duration=timedelta(seconds=1)
        )
    assert first is not None
    async with session_factory() as session, session.begin():
        recovery = await acquire_expired_recovery(
            session,
            recovery_owner="reaper",
            now=now + timedelta(seconds=2),
            lease_duration=timedelta(seconds=10),
            reconcile_deadline=now + timedelta(minutes=1),
        )
    assert recovery is not None
    async with session_factory() as session, session.begin():
        state = await apply_reconcile_result(
            session,
            claim=recovery,
            result=NoEffect(evidence="authoritative absence"),
            now=now + timedelta(seconds=3),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=10),
        )
        assert state is TaskState.RETRY_WAIT
    async with session_factory() as session, session.begin():
        second = await claim_task(
            session,
            owner="worker-2",
            now=now + timedelta(seconds=4),
            lease_duration=timedelta(seconds=10),
        )
    assert second is not None
    assert second.claim_epoch > first.claim_epoch
    assert second.attempt_number == 2


@pytest.mark.asyncio
async def test_attempt_count_matches_append_only_attempt_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, max_attempts=2)
    now = moment()
    async with session_factory() as session, session.begin():
        claim = await claim_task(session, owner="w1", now=now, lease_duration=timedelta(seconds=1))
    assert claim is not None
    async with session_factory() as session, session.begin():
        recovery = await acquire_expired_recovery(
            session,
            recovery_owner="r1",
            now=now + timedelta(seconds=2),
            lease_duration=timedelta(seconds=10),
            reconcile_deadline=now + timedelta(minutes=1),
        )
        assert recovery is not None
        await apply_reconcile_result(
            session,
            claim=recovery,
            result=NoEffect(evidence="absent"),
            now=now + timedelta(seconds=3),
            max_reconcile_checks=3,
            recovery_lease_duration=timedelta(seconds=10),
        )
    async with session_factory() as session, session.begin():
        second = await claim_task(
            session,
            owner="w2",
            now=now + timedelta(seconds=4),
            lease_duration=timedelta(seconds=10),
        )
        assert second is not None
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        rows = await session.scalar(
            select(func.count())
            .select_from(TaskAttemptModel)
            .where(TaskAttemptModel.task_id == seeded.task_id)
        )
        assert task is not None
        assert task.attempt_count == rows == 2


@pytest.mark.asyncio
async def test_fencing_epoch_rejects_fabricated_stale_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_task(session_factory)
    now = moment()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=now, lease_duration=timedelta(seconds=10)
        )
    assert claim is not None
    stale = claim.__class__(
        task_id=claim.task_id,
        attempt_id=claim.attempt_id,
        owner=claim.owner,
        claim_epoch=claim.claim_epoch - 1,
        cancellation_epoch=claim.cancellation_epoch,
        attempt_number=claim.attempt_number,
        lease_expires_at=claim.lease_expires_at,
    )
    async with session_factory() as session, session.begin():
        assert not await finalize_success(session, claim=stale, output={"bad": True}, now=now)
