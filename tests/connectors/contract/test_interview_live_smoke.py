"""Credential-gated Interview MVP live grant probe and RAW/DEV reconciliation."""

from __future__ import annotations

import pytest

from aide.connectors.snowflake.live_probe import (
    interview_live_credentials_available,
    run_live_interview_smoke,
)
from aide.domain.benchmark import LiveSmokeStatus

pytestmark = [
    pytest.mark.snowflake_live,
    pytest.mark.skipif(
        not interview_live_credentials_available(),
        reason="Snowflake RO/DEV credentials unavailable",
    ),
]


@pytest.mark.asyncio
async def test_at18_at19_at24_live_interview_smoke() -> None:
    report = await run_live_interview_smoke()
    assert report.status is LiveSmokeStatus.PASSED, report.detail
    assert report.ro_inspected_raw
    assert report.ro_write_blocked
    assert report.dev_raw_read_blocked
    assert report.dev_raw_write_blocked
    assert report.dev_scope_aide_dev
    assert report.raw_dev_reconciled
    assert report.manifest_digest
    assert report.production_or_staging_action is False
    assert report.grant_sql_executed is False
    assert not report.missing_env_names
