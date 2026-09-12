from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from aide.cli.main import app
from aide.connectors.base.spec import IdentityClass
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV
from aide.connectors.snowflake.config import (
    DEV_IDENTITY_SECRET_NAMES,
    RO_IDENTITY_SECRET_NAMES,
    ROLE_DEVELOPMENT,
    ROLE_READ_ONLY,
    missing_secret_names,
    required_secret_names_for,
    settings_for_identity,
)
from aide.connectors.snowflake.real import RealSnowflakeConnector


def test_ro_and_dev_secretrefs_are_distinct() -> None:
    ro = settings_for_identity(IdentityClass.READ_ONLY)
    dev = settings_for_identity(IdentityClass.DEVELOPMENT)
    assert ro.user.name == "SNOWFLAKE_USER_RO"
    assert ro.private_key.name == "SNOWFLAKE_PRIVATE_KEY_RO"
    assert dev.user.name == "SNOWFLAKE_USER_DEV"
    assert dev.private_key.name == "SNOWFLAKE_PRIVATE_KEY_DEV"
    assert ro.user.name != dev.user.name
    assert ro.private_key.name != dev.private_key.name
    assert ro.account.name == "SNOWFLAKE_ACCOUNT"
    assert dev.account.name == "SNOWFLAKE_ACCOUNT"
    assert ro.warehouse.name == "SNOWFLAKE_WAREHOUSE_DEV"
    assert dev.warehouse.name == "SNOWFLAKE_WAREHOUSE_DEV"
    assert ro.role == ROLE_READ_ONLY
    assert dev.role == ROLE_DEVELOPMENT
    assert set(RO_IDENTITY_SECRET_NAMES).isdisjoint(DEV_IDENTITY_SECRET_NAMES)


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
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_RO" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_ACCOUNT" not in joined


def test_missing_credentials_health_is_unavailable_with_env_names_only() -> None:
    settings = settings_for_identity(IdentityClass.READ_ONLY)
    missing = missing_secret_names(settings)
    assert set(required_secret_names_for(IdentityClass.READ_ONLY)) <= set(missing)
    assert "SNOWFLAKE_USER_RO" in missing
    assert "SNOWFLAKE_PRIVATE_KEY_RO" in missing
    assert "SNOWFLAKE_USER_DEV" not in missing
    assert "SNOWFLAKE_PRIVATE_KEY_DEV" not in missing


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
    ro_joined = " ".join(real_ro["reason_codes"])
    dev_joined = " ".join(real_dev["reason_codes"])
    assert "SECRET_UNRESOLVED:SNOWFLAKE_ACCOUNT" in ro_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_RO" in ro_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_PRIVATE_KEY_RO" in ro_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_WAREHOUSE_DEV" in ro_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_DEV" not in ro_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_RO" not in dev_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_DEV" in dev_joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_PRIVATE_KEY_DEV" in dev_joined
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
    allowed = set(required_secret_names_for(IdentityClass.DEVELOPMENT))
    assert all(
        code.split(":", 1)[1] in allowed
        for code in snapshot.reason_codes
        if code.startswith("SECRET_UNRESOLVED:")
    )
