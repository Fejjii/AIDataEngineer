"""Four-way reconciliation result."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EffectFound(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["EFFECT_FOUND"] = "EFFECT_FOUND"
    output: dict[str, Any]
    external_ref: str | None = None


class NoEffect(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["NO_EFFECT"] = "NO_EFFECT"
    evidence: str = Field(min_length=1)


class InProgress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["IN_PROGRESS"] = "IN_PROGRESS"
    external_ref: str = Field(min_length=1)
    retry_after_seconds: int = Field(ge=0)


class Unknown(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["UNKNOWN"] = "UNKNOWN"
    reason: str = Field(min_length=1)
    evidence: str | None = None


ReconcileResult = Annotated[
    EffectFound | NoEffect | InProgress | Unknown,
    Field(discriminator="kind"),
]
