from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from aide.connectors.base.spec import IdentityClass
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.snowflake.config import ROLE_DEVELOPMENT, ROLE_READ_ONLY
from aide.connectors.snowflake.health import ROLE_MISMATCH
from aide.connectors.snowflake.real import RealSnowflakeConnector


class RoleSessionDouble:
    """Isolated session double. Never opens a Snowflake connection."""

    def __init__(self, role: str | None, *, empty: bool = False) -> None:
        self.role = role
        self.empty = empty
        self.statements: list[str] = []

    def execute(
        self, sql: str, params: object = None
    ) -> tuple[tuple[str, ...], list[dict[str, Any]], str | None]:
        self.statements.append(sql)
        if self.empty:
            return (("ROLE",), [], "qid-health")
        return (("ROLE",), [{"ROLE": self.role}], "qid-health")


def _placeholder_env(monkeypatch: pytest.MonkeyPatch, identity: IdentityClass) -> None:
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "placeholder-account")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE_DEV", "AIDE_DEV_WH")
    if identity is IdentityClass.READ_ONLY:
        monkeypatch.setenv("SNOWFLAKE_USER_RO", "placeholder-ro-user")
        monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_RO", "placeholder-ro-key")
        return
    monkeypatch.setenv("SNOWFLAKE_USER_DEV", "placeholder-dev-user")
    monkeypatch.setenv("SNOWFLAKE_PRIVATE_KEY_DEV", "placeholder-dev-key")


def _run_session(double: RoleSessionDouble) -> Callable[..., Any]:
    async def run_session(*, query_tag: str, timeout_seconds: int, fn: Callable[..., Any]) -> Any:
        return fn(double)

    return run_session


@pytest.mark.asyncio
async def test_health_correct_ro_role(monkeypatch: pytest.MonkeyPatch) -> None:
    _placeholder_env(monkeypatch, IdentityClass.READ_ONLY)
    double = RoleSessionDouble(ROLE_READ_ONLY)
    connector = RealSnowflakeConnector(SNOWFLAKE_RO, run_session=_run_session(double))
    snapshot = await connector.health()
    assert snapshot.status == "AVAILABLE"
    assert ROLE_MISMATCH not in snapshot.reason_codes
    assert any("CURRENT_ROLE" in sql.upper() for sql in double.statements)


@pytest.mark.asyncio
async def test_health_incorrect_ro_role(monkeypatch: pytest.MonkeyPatch) -> None:
    _placeholder_env(monkeypatch, IdentityClass.READ_ONLY)
    double = RoleSessionDouble(ROLE_DEVELOPMENT)
    connector = RealSnowflakeConnector(SNOWFLAKE_RO, run_session=_run_session(double))
    snapshot = await connector.health()
    assert snapshot.status == "UNAVAILABLE"
    assert ROLE_MISMATCH in snapshot.reason_codes


@pytest.mark.asyncio
async def test_health_correct_dev_role(monkeypatch: pytest.MonkeyPatch) -> None:
    _placeholder_env(monkeypatch, IdentityClass.DEVELOPMENT)
    double = RoleSessionDouble(ROLE_DEVELOPMENT)
    connector = RealSnowflakeConnector(SNOWFLAKE_DEV, run_session=_run_session(double))
    snapshot = await connector.health()
    assert snapshot.status == "AVAILABLE"
    assert ROLE_MISMATCH not in snapshot.reason_codes
    assert any("CURRENT_ROLE" in sql.upper() for sql in double.statements)


@pytest.mark.asyncio
async def test_health_incorrect_dev_role(monkeypatch: pytest.MonkeyPatch) -> None:
    _placeholder_env(monkeypatch, IdentityClass.DEVELOPMENT)
    double = RoleSessionDouble(ROLE_READ_ONLY)
    connector = RealSnowflakeConnector(SNOWFLAKE_DEV, run_session=_run_session(double))
    snapshot = await connector.health()
    assert snapshot.status == "UNAVAILABLE"
    assert ROLE_MISMATCH in snapshot.reason_codes
