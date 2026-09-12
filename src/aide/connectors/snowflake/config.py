"""Fake Snowflake settings. SecretRef fields only; no live credentials."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aide.secrets.refs import SecretRef


class FakeSnowflakeSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account: SecretRef | None = None
    user: SecretRef | None = None
    warehouse: str = Field(default="AIDE_DEV_WH")
    dialect: str = "snowflake"
