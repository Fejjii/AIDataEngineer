"""Immutable artifact provenance."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecutionMode(str, Enum):
    REAL = "REAL"
    MOCK = "MOCK"


class ArtifactProvenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_mode: ExecutionMode
    connector_id: str | None
    connector_version: str | None
    capability_id: str = Field(min_length=1)
    capability_version: int = Field(ge=1)
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    parent_artifact_ids: tuple[UUID, ...] = ()

    def is_mock_derived(self) -> bool:
        return self.execution_mode is ExecutionMode.MOCK

    def with_parents(self, parents: tuple[ArtifactProvenance, ...]) -> bool:
        """Return True when this artifact or any ancestor is MOCK-derived."""
        if self.is_mock_derived():
            return True
        return any(parent.with_parents(()) or parent.is_mock_derived() for parent in parents)


def transitive_mock_derived(provenances: tuple[ArtifactProvenance, ...]) -> bool:
    """True when any provenance in the closure is MOCK."""
    return any(item.execution_mode is ExecutionMode.MOCK for item in provenances)
