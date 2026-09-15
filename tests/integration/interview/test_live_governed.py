"""Credential-gated governed live Interview path through the Tool Gateway."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.interview import run_credentialed_live_interview_smoke
from aide.connectors.snowflake.live_probe import interview_live_credentials_available
from aide.domain.benchmark import LiveSmokeStatus

pytestmark = [
    pytest.mark.snowflake_live,
    pytest.mark.dbt_live,
    pytest.mark.skipif(
        not interview_live_credentials_available(),
        reason="Snowflake RO/DEV credentials unavailable",
    ),
]


@pytest.mark.asyncio
async def test_at24_governed_live_interview_uses_tool_gateway(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    report = await run_credentialed_live_interview_smoke(
        session_factory, work_root=tmp_path / "live-governed"
    )
    assert report.status is LiveSmokeStatus.PASSED, report.detail
    assert report.ro_inspected_raw
    assert report.ro_write_blocked
    assert report.dev_raw_read_blocked
    assert report.dev_raw_write_blocked
    assert report.dev_scope_aide_dev
    assert report.raw_dev_reconciled
    assert report.governed_path_exercised
    assert report.policy_evaluated
    assert report.evidence_persisted
    assert report.dev_only_execution
    assert report.tests_ok
    assert report.quality_ok
    assert report.include_schema_drift is False
    assert report.independent_verifier_ran is False
    assert "snowflake_ro" in report.gateway_connector_ids
    assert "snowflake_dev" in report.gateway_connector_ids
    assert "dbt_dev" in report.gateway_connector_ids
    assert report.production_or_staging_action is False
    assert report.grant_sql_executed is False
    assert not report.missing_env_names
