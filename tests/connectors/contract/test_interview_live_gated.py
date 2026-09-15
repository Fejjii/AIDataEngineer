from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.connectors.contract.conftest import clear_snowflake_env

from aide.app.interview import run_credentialed_live_interview_smoke
from aide.connectors.snowflake.live_probe import (
    HUMAN_ACTION,
    LIVE_SECRET_NAMES,
    dev_raw_access_violations,
    interview_live_credentials_available,
    missing_live_secret_names,
    ro_raw_write_violations,
    run_live_interview_smoke,
)
from aide.domain.benchmark import LiveSmokeStatus

_RAW_MUTATION = re.compile(
    r"(?is)\b(?:CREATE(?:\s+OR\s+REPLACE)?|DROP|INSERT(?:\s+INTO)?|UPDATE|"
    r"DELETE(?:\s+FROM)?|MERGE(?:\s+INTO)?|TRUNCATE(?:\s+TABLE)?|ALTER)\b"
    r".{0,160}VANTARA_RAW"
)


def _raw_mutation_windows(source: str) -> list[str]:
    return [match.group(0).split("\n")[0] for match in _RAW_MUTATION.finditer(source)]


def test_live_probe_source_never_issues_grant_sql() -> None:
    source = Path("src/aide/connectors/snowflake/live_probe.py").read_text(encoding="utf-8")
    upper = source.upper()
    assert "GRANT SELECT" not in upper
    assert "GRANT ALL" not in upper
    assert "GRANT USAGE" not in upper
    assert "GRANT OWNERSHIP" not in upper
    assert "REVOKE " not in upper
    assert "ALTER USER" not in upper


def test_live_probe_source_never_mutates_vantara_raw() -> None:
    source = Path("src/aide/connectors/snowflake/live_probe.py").read_text(encoding="utf-8")
    assert not _raw_mutation_windows(source)
    upper = source.upper()
    assert "SHOW GRANTS TO ROLE" in upper
    assert "CREATE TABLE VANTARA_RAW" not in upper
    assert "INSERT INTO VANTARA_RAW" not in upper


def test_live_interview_composition_source_never_mutates_vantara_raw() -> None:
    source = Path("src/aide/app/interview.py").read_text(encoding="utf-8")
    assert not _raw_mutation_windows(source)


def test_ro_select_on_raw_is_not_a_write_violation() -> None:
    grants = (
        {"privilege": "USAGE", "granted_on": "DATABASE", "name": "VANTARA_RAW"},
        {"privilege": "SELECT", "granted_on": "TABLE", "name": "VANTARA_RAW.BILLING.INVOICES"},
    )
    assert ro_raw_write_violations(grants) == ()


def test_ro_insert_on_raw_is_a_write_violation() -> None:
    grants = (
        {"privilege": "INSERT", "granted_on": "TABLE", "name": "VANTARA_RAW.BILLING.INVOICES"},
    )
    assert ro_raw_write_violations(grants)


def test_ro_future_ownership_on_raw_is_a_write_violation() -> None:
    grants = ({"privilege": "OWNERSHIP", "grant_on": "SCHEMA", "name": "VANTARA_RAW.BILLING"},)
    assert ro_raw_write_violations(grants)


def test_dev_usage_on_raw_is_unintended_access() -> None:
    grants = ({"privilege": "USAGE", "granted_on": "DATABASE", "name": "VANTARA_RAW"},)
    assert dev_raw_access_violations(grants)


def test_dev_aide_dev_grants_are_not_raw_access() -> None:
    grants = (
        {"privilege": "CREATE TABLE", "granted_on": "SCHEMA", "name": "AIDE_DEV.WFABC123_BILLING"},
    )
    assert dev_raw_access_violations(grants) == ()


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
    combined = await run_credentialed_live_interview_smoke()
    assert combined.status is LiveSmokeStatus.CREDENTIAL_GATED
    assert combined.missing_env_names
    assert "SNOWFLAKE_ACCOUNT" in combined.human_action
    assert HUMAN_ACTION
    assert combined.grant_sql_executed is False
    assert combined.production_or_staging_action is False
    assert combined.governed_path_exercised is False
