"""Snowflake settings. SecretRef fields only; values never stored on this type."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from aide.connectors.base.spec import IdentityClass
from aide.secrets.refs import SecretRef, SecretScope
from aide.secrets.resolvers import UnresolvedSecretError, assert_scope

REQUIRED_SECRET_NAMES: tuple[str, ...] = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER_DEV",
    "SNOWFLAKE_PRIVATE_KEY_DEV",
    "SNOWFLAKE_WAREHOUSE_DEV",
)

OPTIONAL_SECRET_NAMES: tuple[str, ...] = ("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",)

ROLE_READ_ONLY = "AIDE_DEV_RO"
ROLE_DEVELOPMENT = "AIDE_DEV_RW"


class FakeSnowflakeSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: SecretRef | None = None
    user: SecretRef | None = None
    warehouse: str = Field(default="AIDE_DEV_WH")
    dialect: str = "snowflake"


class SnowflakeSettings(BaseModel):
    """Real connector settings. SecretRef fields only; no secret values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account: SecretRef
    user: SecretRef
    private_key: SecretRef
    warehouse: SecretRef
    role: str
    passphrase: SecretRef | None = None
    database: str | None = None
    dialect: str = "snowflake"

    def required_secret_names(self) -> tuple[str, ...]:
        names = [self.account.name, self.user.name, self.private_key.name, self.warehouse.name]
        return tuple(names)


def _ref(name: str) -> SecretRef:
    return SecretRef(name=name, scope=SecretScope.CONNECTOR)


def settings_for_identity(identity: IdentityClass) -> SnowflakeSettings:
    role = ROLE_READ_ONLY if identity is IdentityClass.READ_ONLY else ROLE_DEVELOPMENT
    passphrase_name = "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"
    passphrase = _ref(passphrase_name) if os.environ.get(passphrase_name) else None
    return SnowflakeSettings(
        account=_ref("SNOWFLAKE_ACCOUNT"),
        user=_ref("SNOWFLAKE_USER_DEV"),
        private_key=_ref("SNOWFLAKE_PRIVATE_KEY_DEV"),
        warehouse=_ref("SNOWFLAKE_WAREHOUSE_DEV"),
        role=role,
        passphrase=passphrase,
    )


def missing_secret_names(settings: SnowflakeSettings) -> tuple[str, ...]:
    """Return unset env var *names* only. Never reads secret values into logs."""
    missing: list[str] = []
    for name in settings.required_secret_names():
        value = os.environ.get(name)
        if value is None or value.strip() == "":
            missing.append(name)
    return tuple(missing)


def snowflake_credentials_available() -> bool:
    return not missing_secret_names(settings_for_identity(IdentityClass.READ_ONLY))


class EnvConnectorSecretResolver:
    """Resolve CONNECTOR-scoped refs from process environment. No enumeration."""

    def resolve(self, ref: SecretRef) -> SecretStr:
        assert_scope(ref, SecretScope.CONNECTOR)
        raw = os.environ.get(ref.name)
        if raw is None or raw.strip() == "":
            raise UnresolvedSecretError(ref.name)
        return SecretStr(raw)
