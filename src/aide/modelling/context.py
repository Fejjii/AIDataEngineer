"""Optional modelling context. Missing fields stay UNKNOWN and are never guessed."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aide.capabilities.io import AuditabilitySignal, CostSensitivity, NamingConvention
from aide.domain.sql import AssetRef


class DimensionHierarchyHint(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entity: str
    levels: tuple[str, ...]
    independent_change_rates: bool = False


class OrgModellingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    auditability: AuditabilitySignal = "UNKNOWN"
    cost_sensitivity: CostSensitivity = "UNKNOWN"
    naming_convention: NamingConvention = "DBT_DEFAULT"


class ModellingContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    org: OrgModellingConfig = Field(default_factory=OrgModellingConfig)
    vendor: str | None = None
    dialect: str | None = None
    catalog_row_counts: tuple[tuple[tuple[str, ...], int], ...] = ()
    existing_layering: str | None = None
    dimension_hierarchies: tuple[DimensionHierarchyHint, ...] = ()
    selected_assets: tuple[AssetRef, ...] = ()
    low_value_scd1_attributes: tuple[tuple[str, str], ...] = ()
    require_demo_models: bool = False
