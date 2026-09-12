from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from aide.cli.main import app
from aide.connectors.base.spec import IdentityClass
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV
from aide.connectors.snowflake.config import REQUIRED_SECRET_NAMES, settings_for_identity
from aide.connectors.snowflake.real import RealSnowflakeConnector


def test_partial_credentials_do_not_echo_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "dummy_account_value_xyz")
    runner = CliRunner()
    result = runner.invoke(app, ["connectors", "check", "--json"])
    assert result.exit_code == 0
    assert "dummy_account_value_xyz" not in result.stdout
    payload = json.loads(result.stdout)
    real_ro = next(
        item for item in payload if item["connector_id"] == "snowflake_ro" and not item["is_fake"]
    )
    joined = " ".join(real_ro["reason_codes"])
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_DEV" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_ACCOUNT" not in joined


def test_missing_credentials_health_is_unavailable_with_env_names_only() -> None:
    settings = settings_for_identity(IdentityClass.READ_ONLY)
    from aide.connectors.snowflake.config import missing_secret_names

    missing = missing_secret_names(settings)
    assert set(REQUIRED_SECRET_NAMES) <= set(missing)


def test_cli_connectors_check_reports_unavailable_without_secret_values() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["connectors", "check", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    by_id = {(item["connector_id"], item["is_fake"]): item for item in payload}
    fake_ro = by_id[("snowflake_ro", True)]
    real_ro = by_id[("snowflake_ro", False)]
    real_dev = by_id[("snowflake_dev", False)]
    assert fake_ro["status"] == "MOCK"
    assert real_ro["status"] == "UNAVAILABLE"
    assert real_dev["status"] == "UNAVAILABLE"
    assert real_ro["identity_class"] == "READ_ONLY"
    assert real_dev["identity_class"] == "DEVELOPMENT"
    joined = " ".join(real_ro["reason_codes"])
    assert "SECRET_UNRESOLVED:SNOWFLAKE_ACCOUNT" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_DEV" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_PRIVATE_KEY_DEV" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_WAREHOUSE_DEV" in joined
    assert "BEGIN" not in result.stdout
    assert "PRIVATE KEY" not in result.stdout
    for item in payload:
        for code in item["reason_codes"]:
            assert not code.startswith("SECRET_UNRESOLVED:") or code.split(":", 1)[1].isupper()


def test_real_dev_health_is_unavailable_when_credentials_absent() -> None:
    import asyncio

    snapshot = asyncio.run(RealSnowflakeConnector(SNOWFLAKE_DEV).health())
    assert snapshot.status == "UNAVAILABLE"
    assert any(code.startswith("SECRET_UNRESOLVED:") for code in snapshot.reason_codes)
    serialized = snapshot.model_dump(mode="json")
    assert "BEGIN" not in str(serialized)
    assert all(
        code.split(":", 1)[1] in REQUIRED_SECRET_NAMES
        for code in snapshot.reason_codes
        if code.startswith("SECRET_UNRESOLVED:")
    )
