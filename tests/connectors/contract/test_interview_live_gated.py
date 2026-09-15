from __future__ import annotations

from pathlib import Path

import pytest
from tests.connectors.contract.conftest import clear_snowflake_env

from aide.connectors.snowflake.live_probe import (
    HUMAN_ACTION,
    LIVE_SECRET_NAMES,
    interview_live_credentials_available,
    missing_live_secret_names,
    run_live_interview_smoke,
)
from aide.domain.benchmark import LiveSmokeStatus


def test_live_probe_source_never_issues_grant_sql() -> None:
    source = Path("src/aide/connectors/snowflake/live_probe.py").read_text(encoding="utf-8")
    upper = source.upper()
    assert "GRANT SELECT" not in upper
    assert "GRANT ALL" not in upper
    assert "GRANT USAGE" not in upper
    assert "GRANT OWNERSHIP" not in upper
    assert "ALTER USER" not in upper


def test_live_secret_names_are_env_names_only() -> None:
    assert "SNOWFLAKE_ACCOUNT" in LIVE_SECRET_NAMES
    assert "SNOWFLAKE_USER_RO" in LIVE_SECRET_NAMES
    assert "SNOWFLAKE_USER_DEV" in LIVE_SECRET_NAMES
    assert all(name.startswith("SNOWFLAKE_") for name in LIVE_SECRET_NAMES)


@pytest.mark.asyncio
async def test_live_smoke_is_credential_gated_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_snowflake_env(monkeypatch)
    assert not interview_live_credentials_available()
    missing = missing_live_secret_names()
    assert "SNOWFLAKE_ACCOUNT" in missing
    assert "SNOWFLAKE_USER_RO" in missing
    assert "SNOWFLAKE_USER_DEV" in missing
    report = await run_live_interview_smoke()
    assert report.status is LiveSmokeStatus.CREDENTIAL_GATED
    assert report.missing_env_names
    assert "SNOWFLAKE_ACCOUNT" in report.human_action
    assert HUMAN_ACTION
    assert report.grant_sql_executed is False
    assert report.production_or_staging_action is False
