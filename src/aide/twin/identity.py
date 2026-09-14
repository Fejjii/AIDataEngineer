"""Stable Twin identity and append-only version materialization."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from aide.domain.twin import (
    SourceAuthorityRef,
    TwinAsset,
    TwinAssetKind,
    TwinEnvironment,
    TwinModel,
    TwinRelationship,
    TwinRelationshipKind,
)


class TwinIdentityError(ValueError):
    """Raised when continuity is ambiguous or contradicts authoritative identity."""


class RenameContinuity(TwinModel):
    """Explicit authoritative proof that a renamed locator is the same object."""

    asset_id: UUID
    evidence_ref_id: UUID
    source_authority: SourceAuthorityRef


class AssetCapture(TwinModel):
    kind: TwinAssetKind
    source_authority: SourceAuthorityRef
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    native_key: str | None = None
    canonical_locator: tuple[str, ...] = Field(min_length=1)
    incarnation: int = Field(default=1, ge=1)
    parent_asset_id: UUID | None = None
    platform_type: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_capture(self) -> AssetCapture:
        if self.native_key == "":
            raise ValueError("native_key cannot be empty")
        if any(not part for part in self.canonical_locator):
            raise ValueError("canonical locator components must be non-empty")
        return self


class RelationshipCapture(TwinModel):
    kind: TwinRelationshipKind
    from_asset_id: UUID
    to_asset_id: UUID
    source_authority: SourceAuthorityRef
    environment: TwinEnvironment = TwinEnvironment.DEVELOPMENT
    confidence: float = Field(ge=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    evidence_ref_id: UUID


def materialize_asset_version(
    capture: AssetCapture,
    *,
    existing_versions: tuple[TwinAsset, ...] = (),
    identity_asset_id: UUID | None = None,
) -> TwinAsset:
    """Return the existing semantic version or append the next immutable version."""
    ordered = tuple(sorted(existing_versions, key=lambda item: item.asset_version))
    if ordered:
        asset_ids = {item.asset_id for item in ordered}
        if len(asset_ids) != 1:
            raise TwinIdentityError("existing versions contain more than one asset identity")
        if identity_asset_id is not None and identity_asset_id not in asset_ids:
            raise TwinIdentityError("resolved identity disagrees with existing versions")
        latest = ordered[-1]
        _validate_asset_identity(capture, latest)
        if _asset_facts_equal(latest, capture):
            return latest
        asset_id = latest.asset_id
        version = latest.asset_version + 1
        first_observed_at = ordered[0].first_observed_at
    else:
        asset_id = identity_asset_id or uuid4()
        version = 1
        first_observed_at = capture.observed_at
    return TwinAsset(
        asset_id=asset_id,
        asset_version=version,
        kind=capture.kind,
        source_authority=capture.source_authority,
        environment=capture.environment,
        native_key=capture.native_key,
        canonical_locator=capture.canonical_locator,
        parent_asset_id=capture.parent_asset_id,
        platform_type=capture.platform_type,
        attributes=capture.attributes,
        first_observed_at=first_observed_at,
        observed_at=capture.observed_at,
        evidence_ref_id=capture.evidence_ref_id,
    )


def materialize_relationship_version(
    capture: RelationshipCapture,
    *,
    existing_versions: tuple[TwinRelationship, ...] = (),
    relationship_id: UUID | None = None,
) -> TwinRelationship:
    """Return an unchanged relationship or append its next immutable version."""
    ordered = tuple(sorted(existing_versions, key=lambda item: item.relationship_version))
    if ordered:
        relationship_ids = {item.relationship_id for item in ordered}
        if len(relationship_ids) != 1:
            raise TwinIdentityError("existing versions contain multiple relationship identities")
        latest = ordered[-1]
        if relationship_id is not None and latest.relationship_id != relationship_id:
            raise TwinIdentityError("resolved relationship identity disagrees with history")
        if _relationship_facts_equal(latest, capture):
            return latest
        resolved_id = latest.relationship_id
        version = latest.relationship_version + 1
    else:
        resolved_id = relationship_id or uuid4()
        version = 1
    return TwinRelationship(
        relationship_id=resolved_id,
        relationship_version=version,
        kind=capture.kind,
        from_asset_id=capture.from_asset_id,
        to_asset_id=capture.to_asset_id,
        source_authority=capture.source_authority,
        environment=capture.environment,
        confidence=capture.confidence,
        attributes=capture.attributes,
        observed_at=capture.observed_at,
        evidence_ref_id=capture.evidence_ref_id,
    )


def _validate_asset_identity(capture: AssetCapture, latest: TwinAsset) -> None:
    identity_fields = (
        capture.kind == latest.kind,
        capture.source_authority == latest.source_authority,
        capture.environment == latest.environment,
    )
    if not all(identity_fields):
        raise TwinIdentityError("a version cannot change kind, authority, or environment")


def _asset_facts_equal(asset: TwinAsset, capture: AssetCapture) -> bool:
    return (
        asset.kind == capture.kind
        and asset.source_authority == capture.source_authority
        and asset.environment == capture.environment
        and asset.native_key == capture.native_key
        and asset.canonical_locator == capture.canonical_locator
        and asset.parent_asset_id == capture.parent_asset_id
        and asset.platform_type == capture.platform_type
        and asset.attributes == capture.attributes
        and asset.evidence_ref_id == capture.evidence_ref_id
    )


def _relationship_facts_equal(relationship: TwinRelationship, capture: RelationshipCapture) -> bool:
    return (
        relationship.kind == capture.kind
        and relationship.from_asset_id == capture.from_asset_id
        and relationship.to_asset_id == capture.to_asset_id
        and relationship.source_authority == capture.source_authority
        and relationship.environment == capture.environment
        and relationship.confidence == capture.confidence
        and relationship.attributes == capture.attributes
        and relationship.evidence_ref_id == capture.evidence_ref_id
    )


__all__ = [
    "AssetCapture",
    "RelationshipCapture",
    "RenameContinuity",
    "TwinIdentityError",
    "materialize_asset_version",
    "materialize_relationship_version",
]
