"""Connector advertisements, identity class, and version compatibility."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.sql import AssetRef


class ConnectorKind(str, Enum):
    WAREHOUSE = "warehouse"
    DATABASE = "database"
    TRANSFORMATION = "transformation"
    VCS = "vcs"
    ORCHESTRATION = "orchestration"
    STORAGE = "storage"
    API_SOURCE = "api_source"
    STREAMING = "streaming"
    BI = "bi"
    CATALOG = "catalog"


class IdentityClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    DEVELOPMENT = "DEVELOPMENT"
    STAGING_DEPLOY = "STAGING_DEPLOY"
    VCS = "VCS"


class CapabilityImplementation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str = Field(min_length=1)
    supported_contract_versions: frozenset[int]
    input_schema_versions: frozenset[int]
    output_schema_versions: frozenset[int]


class ObjectAllowList(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    databases: frozenset[str] = frozenset()
    schemas: frozenset[tuple[str, str]] = frozenset()
    objects: frozenset[tuple[str, ...]] = frozenset()
    repos: frozenset[str] = frozenset()

    def contains_asset(self, asset: AssetRef) -> bool:
        address = asset.address
        if address in self.objects:
            return True
        if len(address) >= 1 and address[0] in self.databases:
            if len(address) == 1:
                return True
            if len(address) >= 2 and (address[0], address[1]) in self.schemas:
                return True
            if not self.schemas:
                return True
        if len(address) >= 2 and (address[0], address[1]) in self.schemas:
            return True
        if asset.kind.value == "FILE" or asset.platform_type == "repo":
            return "/".join(address) in self.repos or (
                address[-1] in self.repos if address else False
            )
        return False


class ConnectorSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: str = Field(min_length=1)
    kind: ConnectorKind
    vendor: str = Field(min_length=1)
    version: str = Field(min_length=1)
    target_environment: TargetEnv
    identity_class: IdentityClass
    implementations: frozenset[CapabilityImplementation]
    allowed_permissions: frozenset[PermissionLevel]
    allow_list: ObjectAllowList
    dialect: str | None = None
    is_fake: bool = False

    def advertises(self, capability_id: str, version: int | None = None) -> bool:
        for impl in self.implementations:
            if impl.capability_id != capability_id:
                continue
            if version is None or version in impl.supported_contract_versions:
                return True
        return False

    def implementation(self, capability_id: str) -> CapabilityImplementation | None:
        for impl in self.implementations:
            if impl.capability_id == capability_id:
                return impl
        return None


def versions_compatible(
    advertisement: CapabilityImplementation,
    *,
    contract_version: int,
    input_schema_version: int,
    output_schema_version: int,
) -> bool:
    return (
        contract_version in advertisement.supported_contract_versions
        and input_schema_version in advertisement.input_schema_versions
        and output_schema_version in advertisement.output_schema_versions
    )
