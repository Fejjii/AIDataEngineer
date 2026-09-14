"""Provider-neutral contracts for the minimal Enterprise Data Digital Twin."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class TwinModel(BaseModel):
    """Immutable, closed Pydantic base for published Twin contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TwinEnvironment(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"


class TwinAssetKind(str, Enum):
    DATASET = "DATASET"
    FIELD = "FIELD"
    TRANSFORMATION = "TRANSFORMATION"
    TEST = "TEST"


class TwinRelationshipKind(str, Enum):
    CONTAINS = "CONTAINS"
    TRANSFORMS_FROM = "TRANSFORMS_FROM"
    TESTS = "TESTS"
    MATERIALIZED_FROM = "MATERIALIZED_FROM"


class TwinObservationKind(str, Enum):
    SCHEMA = "SCHEMA"
    PROFILE_SUMMARY = "PROFILE_SUMMARY"
    FRESHNESS = "FRESHNESS"
    EXECUTION_RESULT = "EXECUTION_RESULT"
    TEST_RESULT = "TEST_RESULT"
    DRIFT = "DRIFT"


class SourceAuthorityRef(TwinModel):
    """Configured authority identity, contract version, and bounded scope."""

    authority_id: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    scope: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> SourceAuthorityRef:
        if any(not part for part in self.scope):
            raise ValueError("source authority scope components must be non-empty")
        return self

    def sort_key(self) -> tuple[str, str, tuple[str, ...]]:
        return self.authority_id, self.contract_version, self.scope


class TwinAsset(TwinModel):
    asset_id: UUID
    asset_version: int = Field(ge=1)
    kind: TwinAssetKind
    source_authority: SourceAuthorityRef
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    native_key: str | None = None
    canonical_locator: tuple[str, ...] = Field(min_length=1)
    parent_asset_id: UUID | None = None
    platform_type: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    first_observed_at: datetime
    observed_at: datetime
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_asset(self) -> TwinAsset:
        if any(not part for part in self.canonical_locator):
            raise ValueError("canonical locator components must be non-empty")
        if self.parent_asset_id == self.asset_id:
            raise ValueError("an asset cannot be its own parent")
        if self.observed_at < self.first_observed_at:
            raise ValueError("observed_at cannot precede first_observed_at")
        if self.native_key == "":
            raise ValueError("native_key cannot be empty")
        return self


class TwinRelationship(TwinModel):
    relationship_id: UUID
    relationship_version: int = Field(ge=1)
    kind: TwinRelationshipKind
    from_asset_id: UUID
    to_asset_id: UUID
    source_authority: SourceAuthorityRef
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    confidence: float = Field(ge=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_relationship(self) -> TwinRelationship:
        if self.from_asset_id == self.to_asset_id:
            raise ValueError("a Twin relationship cannot be a self-loop")
        return self


class TwinObservation(TwinModel):
    observation_id: UUID
    subject_asset_id: UUID
    kind: TwinObservationKind
    source_authority: SourceAuthorityRef
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    value: dict[str, Any]
    observed_at: datetime
    effective_at: datetime | None = None
    fresh_until: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_freshness_window(self) -> TwinObservation:
        if self.fresh_until is not None and self.fresh_until < self.observed_at:
            raise ValueError("fresh_until cannot precede observed_at")
        return self


class EvidenceReference(TwinModel):
    evidence_ref_id: UUID
    evidence_type: str = Field(min_length=1)
    artifact_id: UUID | None = None
    immutable_uri: str | None = None
    media_type: str = Field(min_length=1)
    sha256: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    execution_mode: str
    source_authority: SourceAuthorityRef
    producer_operation_key: str | None = None
    producer_attempt_id: UUID | None = None
    created_at: datetime

    @model_validator(mode="after")
    def validate_execution_mode(self) -> EvidenceReference:
        if self.execution_mode not in {"REAL", "MOCK"}:
            raise ValueError("execution_mode must be REAL or MOCK")
        if self.producer_operation_key is not None:
            if len(self.producer_operation_key) != 64:
                raise ValueError("producer_operation_key must be a 64-character digest")
            if any(char not in "0123456789abcdef" for char in self.producer_operation_key):
                raise ValueError("producer_operation_key must be lowercase hexadecimal")
        return self


class TwinSnapshot(TwinModel):
    twin_snapshot_id: UUID
    schema_version: int = Field(ge=1)
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    captured_at: datetime
    capture_cutoff: datetime
    asset_versions: tuple[tuple[UUID, int], ...]
    relationship_versions: tuple[tuple[UUID, int], ...]
    observation_ids: tuple[UUID, ...]
    evidence_reference_ids: tuple[UUID, ...]
    source_authorities: tuple[SourceAuthorityRef, ...]
    manifest_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_manifest_membership(self) -> TwinSnapshot:
        if self.capture_cutoff > self.captured_at:
            raise ValueError("capture_cutoff cannot be after captured_at")
        if self.asset_versions != tuple(sorted(set(self.asset_versions), key=_version_key)):
            raise ValueError("asset_versions must be sorted and unique")
        if self.relationship_versions != tuple(
            sorted(set(self.relationship_versions), key=_version_key)
        ):
            raise ValueError("relationship_versions must be sorted and unique")
        if self.observation_ids != tuple(sorted(set(self.observation_ids), key=str)):
            raise ValueError("observation_ids must be sorted and unique")
        if self.evidence_reference_ids != tuple(sorted(set(self.evidence_reference_ids), key=str)):
            raise ValueError("evidence_reference_ids must be sorted and unique")
        expected_authorities = tuple(
            sorted(set(self.source_authorities), key=SourceAuthorityRef.sort_key)
        )
        if self.source_authorities != expected_authorities:
            raise ValueError("source_authorities must be sorted and unique")
        return self


class EstateContext(TwinModel):
    """Canonical, permission-filtered reasoner input pinned to one snapshot."""

    schema_version: int = Field(default=1, ge=1)
    twin_snapshot_id: UUID
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    assets: tuple[TwinAsset, ...]
    relationships: tuple[TwinRelationship, ...]
    observations: tuple[TwinObservation, ...]
    evidence_references: tuple[EvidenceReference, ...]
    source_authorities: tuple[SourceAuthorityRef, ...]
    estate_context_sha256: str = Field(pattern=SHA256_PATTERN)


def _version_key(member: tuple[UUID, int]) -> tuple[str, int]:
    return str(member[0]), member[1]


__all__ = [
    "EstateContext",
    "EvidenceReference",
    "SHA256_PATTERN",
    "SourceAuthorityRef",
    "TwinAsset",
    "TwinAssetKind",
    "TwinEnvironment",
    "TwinObservation",
    "TwinObservationKind",
    "TwinRelationship",
    "TwinRelationshipKind",
    "TwinSnapshot",
]
