from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.evidence import validate_persisted_evidence
from aide.app.benchmarking.runner import run_interview_once
from aide.persistence.database import create_engine, create_session_factory

SYNC_DATABASE_URL = os.getenv(
    "AIDE_TEST_DATABASE_URL",
    "postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev",
)


@pytest.mark.asyncio
async def test_evidence_remains_queryable_after_new_engine(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    result = await run_interview_once(session_factory, tmp_path)
    assert result.verifier is not None
    claimed = result.extra.get("evidence_bundle_sha256")
    assert isinstance(claimed, str)
    first_complete, first_digest = await validate_persisted_evidence(
        session_factory,
        result.workflow_id,
        claimed_bundle_sha256=claimed,
    )
    assert first_complete.complete
    assert first_complete.completeness_pct == 100

    restarted = create_engine(SYNC_DATABASE_URL)
    try:
        restarted_factory = create_session_factory(restarted)
        second_complete, second_digest = await validate_persisted_evidence(
            restarted_factory,
            result.workflow_id,
            claimed_bundle_sha256=claimed,
        )
    finally:
        await restarted.dispose()

    assert second_complete.complete
    assert second_complete.completeness_pct == 100
    assert second_digest == first_digest
    assert second_digest == claimed
