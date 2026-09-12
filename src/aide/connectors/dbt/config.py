"""dbt connector settings. SecretRef fields only; values never stored here."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from aide.secrets.refs import SecretRef, SecretScope

SNOWFLAKE_DBT_SECRET_NAMES: tuple[str, ...] = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER_DEV",
    "SNOWFLAKE_PRIVATE_KEY_DEV",
    "SNOWFLAKE_WAREHOUSE_DEV",
)

ADAPTER_DUCKDB = "duckdb"
ADAPTER_SNOWFLAKE = "snowflake"


class DbtAdapter(str, Enum):
    DUCKDB = "duckdb"
    SNOWFLAKE = "snowflake"


def _ref(name: str) -> SecretRef:
    return SecretRef(name=name, scope=SecretScope.CONNECTOR)


class DbtSettings(BaseModel):
    """Real connector settings. Secret values are never stored on this object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter: DbtAdapter = DbtAdapter.DUCKDB
    work_root: Path
    project_template: Path | None = None
    duckdb_path: Path | None = None
    timeout_seconds: int = Field(default=180, ge=1)
    profile_name: str = "vantara"
    target_name: str = "dev"
    threads: int = Field(default=1, ge=1)
    snowflake_account: SecretRef | None = None
    snowflake_user: SecretRef | None = None
    snowflake_private_key: SecretRef | None = None
    snowflake_warehouse: SecretRef | None = None
    snowflake_database: str = "AIDE_DEV"
    snowflake_schema: str = "AIDE_DEV"
    snowflake_role: str = "AIDE_DEV_RW"

    def required_secret_names(self) -> tuple[str, ...]:
        if self.adapter is DbtAdapter.DUCKDB:
            return ()
        names = [
            (self.snowflake_account or _ref("SNOWFLAKE_ACCOUNT")).name,
            (self.snowflake_user or _ref("SNOWFLAKE_USER_DEV")).name,
            (self.snowflake_private_key or _ref("SNOWFLAKE_PRIVATE_KEY_DEV")).name,
            (self.snowflake_warehouse or _ref("SNOWFLAKE_WAREHOUSE_DEV")).name,
        ]
        return tuple(names)


def missing_secret_names(settings: DbtSettings) -> tuple[str, ...]:
    """Return unset env var *names* only. Never reads secret values into logs."""
    missing: list[str] = []
    for name in settings.required_secret_names():
        value = os.environ.get(name)
        if value is None or value.strip() == "":
            missing.append(name)
    return tuple(missing)


def snowflake_dbt_settings(work_root: Path, *, project_template: Path | None = None) -> DbtSettings:
    return DbtSettings(
        adapter=DbtAdapter.SNOWFLAKE,
        work_root=work_root,
        project_template=project_template,
        snowflake_account=_ref("SNOWFLAKE_ACCOUNT"),
        snowflake_user=_ref("SNOWFLAKE_USER_DEV"),
        snowflake_private_key=_ref("SNOWFLAKE_PRIVATE_KEY_DEV"),
        snowflake_warehouse=_ref("SNOWFLAKE_WAREHOUSE_DEV"),
    )


def render_profiles_yaml(settings: DbtSettings) -> str:
    """Generate profiles.yml. Secrets are referenced by env var name only."""
    if settings.adapter is DbtAdapter.DUCKDB:
        return (
            f"{settings.profile_name}:\n"
            f"  target: {settings.target_name}\n"
            f"  outputs:\n"
            f"    {settings.target_name}:\n"
            f"      type: duckdb\n"
            f"      path: \"{{{{ env_var('AIDE_DBT_DUCKDB_PATH') }}}}\"\n"
            f"      schema: AIDE_DEV\n"
            f"      threads: {settings.threads}\n"
        )
    account = (settings.snowflake_account or _ref("SNOWFLAKE_ACCOUNT")).name
    user = (settings.snowflake_user or _ref("SNOWFLAKE_USER_DEV")).name
    private_key = (settings.snowflake_private_key or _ref("SNOWFLAKE_PRIVATE_KEY_DEV")).name
    warehouse = (settings.snowflake_warehouse or _ref("SNOWFLAKE_WAREHOUSE_DEV")).name
    return (
        f"{settings.profile_name}:\n"
        f"  target: {settings.target_name}\n"
        f"  outputs:\n"
        f"    {settings.target_name}:\n"
        f"      type: snowflake\n"
        f"      account: \"{{{{ env_var('{account}') }}}}\"\n"
        f"      user: \"{{{{ env_var('{user}') }}}}\"\n"
        f"      private_key: \"{{{{ env_var('{private_key}') }}}}\"\n"
        f"      warehouse: \"{{{{ env_var('{warehouse}') }}}}\"\n"
        f"      database: {settings.snowflake_database}\n"
        f"      schema: {settings.snowflake_schema}\n"
        f"      role: {settings.snowflake_role}\n"
        f"      threads: {settings.threads}\n"
        f"      client_session_keep_alive: False\n"
    )


def duckdb_dbt_settings(
    work_root: Path,
    *,
    duckdb_path: Path | None = None,
    project_template: Path | None = None,
    timeout_seconds: int = 180,
) -> DbtSettings:
    return DbtSettings(
        adapter=DbtAdapter.DUCKDB,
        work_root=work_root,
        project_template=project_template,
        duckdb_path=duckdb_path,
        timeout_seconds=timeout_seconds,
    )
