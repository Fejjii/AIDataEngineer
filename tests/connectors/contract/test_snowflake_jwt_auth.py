from __future__ import annotations

from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from pydantic import SecretStr
from snowflake.connector.network import KEY_PAIR_AUTHENTICATOR as VENDOR_KEY_PAIR_AUTHENTICATOR

from aide.connectors.base.spec import IdentityClass
from aide.connectors.snowflake.config import settings_for_identity
from aide.connectors.snowflake.session import (
    KEY_PAIR_AUTHENTICATOR,
    SnowflakeSession,
    connect_kwargs,
)


class _DummyConnection:
    def close(self) -> None:
        return


def _ephemeral_pem() -> SecretStr:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    return SecretStr(pem.decode("utf-8"))


def test_key_pair_authenticator_matches_installed_connector() -> None:
    assert KEY_PAIR_AUTHENTICATOR == "SNOWFLAKE_JWT"
    assert KEY_PAIR_AUTHENTICATOR == VENDOR_KEY_PAIR_AUTHENTICATOR


def test_connect_kwargs_use_snowflake_jwt() -> None:
    kwargs = connect_kwargs(
        account="placeholder-account",
        user="placeholder-user",
        private_key=b"placeholder-der",
        warehouse="placeholder-warehouse",
        role="AIDE_DEV_RO",
        database=None,
        query_tag="aide:v1;health",
        timeout_seconds=15,
    )
    assert kwargs["authenticator"] == "SNOWFLAKE_JWT"
    assert kwargs["authenticator"] != "SNOWFLAKE"


def test_real_session_passes_snowflake_jwt_to_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> _DummyConnection:
        captured.update(kwargs)
        return _DummyConnection()

    import snowflake.connector

    monkeypatch.setattr(snowflake.connector, "connect", fake_connect)
    SnowflakeSession(
        settings_for_identity(IdentityClass.READ_ONLY),
        account=SecretStr("placeholder-account"),
        user=SecretStr("placeholder-user"),
        private_key=_ephemeral_pem(),
        warehouse=SecretStr("placeholder-warehouse"),
        passphrase=None,
        query_tag="aide:v1;health",
        timeout_seconds=15,
    )
    assert captured["authenticator"] == "SNOWFLAKE_JWT"
    assert isinstance(captured["private_key"], bytes)
    assert captured["private_key"]
    assert "BEGIN" not in str(captured["authenticator"])
