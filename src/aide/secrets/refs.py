"""SecretRef indirection. Values never appear on this type."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class SecretScope(str, Enum):
    CONNECTOR = "CONNECTOR"
    LLM_PROVIDER = "LLM_PROVIDER"


class SecretRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, pattern=r"^[A-Z][A-Z0-9_]+$")
    scope: SecretScope
