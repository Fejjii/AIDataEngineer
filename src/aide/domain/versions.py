"""Pinned contract snapshot types."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CapabilityContractRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1)
    capability_contract_version: int = Field(ge=1)
    input_schema_version: int = Field(ge=1)
    output_schema_version: int = Field(ge=1)


class ContractSnapshot(BaseModel):
    """Immutable map of capability/schema/connector versions for one phase run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    capability_contracts: tuple[CapabilityContractRef, ...]
    connector_versions: dict[str, str] = Field(default_factory=dict)

    def capability(self, capability_id: str) -> CapabilityContractRef | None:
        for item in self.capability_contracts:
            if item.capability_id == capability_id:
                return item
        return None

    def connector_version(self, connector_id: str) -> str | None:
        return self.connector_versions.get(connector_id)
