"""Provider-neutral pending capture records shared with persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, model_validator

from aide.domain.twin import (
    SourceAuthorityRef,
    TwinAssetKind,
    TwinEnvironment,
    TwinModel,
    TwinObservationKind,
    TwinRelationshipKind,
)
from aide.twin.identity import AssetCapture, RelationshipCapture


class PendingAssetCapture(TwinModel):
    capture_key: str = Field(min_length=1)
    kind: TwinAssetKind
    source_authority: SourceAuthorityRef
    native_key: str | None = None
    canonical_locator: tuple[str, ...] = Field(min_length=1)
    incarnation: int = Field(default=1, ge=1)
    parent_capture_key: str | None = None
    parent_asset_id: UUID | None = None
    platform_type: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_parent(self) -> PendingAssetCapture:
        if self.parent_capture_key is not None and self.parent_asset_id is not None:
            raise ValueError("pending asset parent must use a capture key or asset ID, not both")
        return self

    def resolved(self, *, parent_asset_id: UUID | None = None) -> AssetCapture:
        return AssetCapture(
            kind=self.kind,
            source_authority=self.source_authority,
            environment=TwinEnvironment.DEVELOPMENT,
            native_key=self.native_key,
            canonical_locator=self.canonical_locator,
            incarnation=self.incarnation,
            parent_asset_id=self.parent_asset_id or parent_asset_id,
            platform_type=self.platform_type,
            attributes=self.attributes,
            observed_at=self.observed_at,
            evidence_ref_id=self.evidence_ref_id,
        )


class PendingRelationshipCapture(TwinModel):
    capture_key: str = Field(min_length=1)
    kind: TwinRelationshipKind
    from_capture_key: str | None = None
    from_asset_id: UUID | None = None
    to_capture_key: str | None = None
    to_asset_id: UUID | None = None
    source_authority: SourceAuthorityRef
    confidence: float = Field(ge=0, le=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    observed_at: datetime
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_endpoints(self) -> PendingRelationshipCapture:
        if (self.from_capture_key is None) == (self.from_asset_id is None):
            raise ValueError("from endpoint must use exactly one capture key or asset ID")
        if (self.to_capture_key is None) == (self.to_asset_id is None):
            raise ValueError("to endpoint must use exactly one capture key or asset ID")
        return self

    def resolved(
        self, *, from_asset_id: UUID | None = None, to_asset_id: UUID | None = None
    ) -> RelationshipCapture:
        resolved_from = self.from_asset_id or from_asset_id
        resolved_to = self.to_asset_id or to_asset_id
        if resolved_from is None or resolved_to is None:
            raise ValueError("relationship capture endpoints are unresolved")
        return RelationshipCapture(
            kind=self.kind,
            from_asset_id=resolved_from,
            to_asset_id=resolved_to,
            source_authority=self.source_authority,
            environment=TwinEnvironment.DEVELOPMENT,
            confidence=self.confidence,
            attributes=self.attributes,
            observed_at=self.observed_at,
            evidence_ref_id=self.evidence_ref_id,
        )


class PendingObservationCapture(TwinModel):
    subject_capture_key: str | None = None
    subject_asset_id: UUID | None = None
    kind: TwinObservationKind
    source_authority: SourceAuthorityRef
    value: dict[str, Any]
    observed_at: datetime
    effective_at: datetime | None = None
    fresh_until: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    evidence_ref_id: UUID

    @model_validator(mode="after")
    def validate_subject(self) -> PendingObservationCapture:
        if (self.subject_capture_key is None) == (self.subject_asset_id is None):
            raise ValueError("observation subject must use exactly one capture key or asset ID")
        return self


class TwinCaptureBatch(TwinModel):
    assets: tuple[PendingAssetCapture, ...] = ()
    relationships: tuple[PendingRelationshipCapture, ...] = ()
    observations: tuple[PendingObservationCapture, ...] = ()

    @model_validator(mode="after")
    def validate_capture_keys(self) -> TwinCaptureBatch:
        keys = [item.capture_key for item in self.assets]
        if len(keys) != len(set(keys)):
            raise ValueError("asset capture keys must be unique")
        available = set(keys)
        for asset in self.assets:
            if asset.parent_capture_key is not None and asset.parent_capture_key not in available:
                raise ValueError(f"unknown parent capture key: {asset.parent_capture_key}")
        for relationship in self.relationships:
            endpoints = (relationship.from_capture_key, relationship.to_capture_key)
            if any(item is not None and item not in available for item in endpoints):
                raise ValueError("relationship refers to an unknown capture key")
        for observation in self.observations:
            key = observation.subject_capture_key
            if key is not None and key not in available:
                raise ValueError(f"observation refers to unknown capture key: {key}")
        return self


__all__ = [
    "PendingAssetCapture",
    "PendingObservationCapture",
    "PendingRelationshipCapture",
    "TwinCaptureBatch",
]
