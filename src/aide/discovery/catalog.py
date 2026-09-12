"""Immutable metadata catalogue for discovery enumeration."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.capabilities.io import CatalogAsset
from aide.domain.sql import AssetRef


class MetadataCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: UUID
    assets: tuple[CatalogAsset, ...] = Field(default_factory=tuple)

    @classmethod
    def from_assets(cls, snapshot_id: UUID, assets: tuple[CatalogAsset, ...]) -> MetadataCatalog:
        ordered = tuple(sorted(assets, key=lambda item: item.address))
        return cls(snapshot_id=snapshot_id, assets=ordered)

    def asset_refs(self) -> tuple[AssetRef, ...]:
        return tuple(
            AssetRef(
                connector_id=item.connector_id,
                address=item.address,
                kind=item.kind,
                platform_type=item.platform_type,
            )
            for item in self.assets
        )

    def contains(self, asset: AssetRef) -> bool:
        return any(
            item.connector_id == asset.connector_id and item.address == asset.address
            for item in self.assets
        )
