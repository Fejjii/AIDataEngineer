"""Typed capability input/output schemas for the DE 002C slice."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.sql import AssetKind, AssetRef, SqlClassification, SqlText
from aide.domain.states import WorkflowState


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Budget(FrozenModel):
    max_rows: int = Field(ge=1)
    max_bytes: int = Field(ge=1)
    max_seconds: int = Field(ge=1)


class DiscoveryScope(FrozenModel):
    databases: tuple[str, ...]
    schemas: tuple[str, ...] | None = None
    include_views: bool = False


class DiscoveryFilters(FrozenModel):
    name_pattern: str | None = None


class DiscoverAssetsInput(FrozenModel):
    scope: DiscoveryScope
    filters: DiscoveryFilters = Field(default_factory=DiscoveryFilters)


class CatalogAsset(FrozenModel):
    connector_id: str
    address: tuple[str, ...]
    kind: AssetKind
    platform_type: str | None = None
    row_count_estimate: int | None = None
    last_altered: datetime | None = None
    comment: str | None = None


class DiscoverAssetsOutput(FrozenModel):
    assets: tuple[CatalogAsset, ...]
    snapshot_id: UUID
    truncated: bool = False


class DescribeAssetInput(FrozenModel):
    asset: AssetRef
    include_constraints: bool = True
    include_row_count: bool = True


class ColumnSpec(FrozenModel):
    name: str
    data_type: str
    nullable: bool
    ordinal: int
    comment: str | None = None
    is_untrusted_text: bool = True


class ForeignKeySpec(FrozenModel):
    columns: tuple[str, ...]
    ref_asset: AssetRef
    ref_columns: tuple[str, ...]


class DescribeAssetOutput(FrozenModel):
    asset: AssetRef
    columns: tuple[ColumnSpec, ...]
    primary_key: tuple[str, ...] | None = None
    unique_keys: tuple[tuple[str, ...], ...] = ()
    foreign_keys: tuple[ForeignKeySpec, ...] = ()
    row_count: int | None = None
    clustering: tuple[str, ...] | None = None
    snapshot_id: UUID


class ClassifySqlInput(FrozenModel):
    sql: SqlText


class ClassifySqlOutput(SqlClassification):
    pass


class ValidateQueryInput(FrozenModel):
    sql: SqlText
    mode: Literal["EXPLAIN", "COMPILE"] = "EXPLAIN"


class QueryError(FrozenModel):
    code: str | None = None
    message: str
    line: int | None = None
    object: str | None = None


class PlanSummary(FrozenModel):
    estimated_bytes: int | None = None
    partitions_total: int | None = None
    partitions_scanned: int | None = None


class ValidateQueryOutput(FrozenModel):
    valid: bool
    error: QueryError | None = None
    plan_summary: PlanSummary | None = None


class ExecuteQueryInput(FrozenModel):
    sql: SqlText
    budget: Budget
    result_mode: Literal["ROWS", "SCALAR", "COUNT_ONLY"] = "ROWS"


class ExecuteQueryOutput(FrozenModel):
    rows: tuple[dict[str, Any], ...] | None = None
    scalar: Any | None = None
    row_count: int
    bytes_scanned: int | None = None
    duration_ms: int
    query_id: str | None = None
    query_tag: str | None = None
    truncated: bool = False


class CreateDatasetInput(FrozenModel):
    target: AssetRef
    definition: SqlText
    replace: bool = False


class CreateDatasetOutput(FrozenModel):
    created: AssetRef
    replaced_existing: bool
    row_count: int | None = None


class ClarificationPair(FrozenModel):
    question: str
    answer: str


class GlossaryTerm(FrozenModel):
    term: str
    definition: str


class InterpretRequirementInput(FrozenModel):
    text: str = Field(min_length=1, max_length=8000)
    prior_clarifications: tuple[ClarificationPair, ...] = ()
    organisation_glossary: tuple[GlossaryTerm, ...] | None = None


class BusinessEntity(FrozenModel):
    name: str
    description: str


class MetricSpec(FrozenModel):
    name: str
    definition: str | None = None
    ambiguous: bool = False


class Ambiguity(FrozenModel):
    topic: str
    question: str
    options: tuple[str, ...] = ()
    blocking: bool = False


class RequirementSpec(FrozenModel):
    goal: str
    deliverable_type: Literal[
        "ANALYTICAL_DATA_PRODUCT",
        "PIPELINE",
        "MODEL_CHANGE",
        "QUALITY_SUITE",
        "INVESTIGATION",
    ]
    business_entities: tuple[BusinessEntity, ...] = ()
    metrics: tuple[MetricSpec, ...] = ()
    grain_hints: tuple[str, ...] = ()
    history_requirements: Literal["NONE", "CURRENT_ONLY", "FULL_HISTORY", "UNKNOWN"] = "UNKNOWN"
    freshness_requirement: str | None = None
    consumers: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    ambiguities: tuple[Ambiguity, ...] = ()
    out_of_scope: tuple[str, ...] = ()


class CapabilityCatalogueEntry(FrozenModel):
    id: str
    version: int
    purpose: str
    permission: str
    risk: str
    input_schema_version: int


class RegisteredConnector(FrozenModel):
    connector_id: str
    kind: str
    supported_contract_versions: tuple[int, ...]
    identity_class: str | None = None


class PlanConstraints(FrozenModel):
    max_tasks: int = 50
    effective_grants: tuple[str, ...] = ()
    registered_connectors: tuple[RegisteredConnector, ...] = ()


class PlanPhaseInput(FrozenModel):
    workflow_context_ref: str
    phase: WorkflowState
    contract_snapshot_ref: str
    capability_catalogue: tuple[CapabilityCatalogueEntry, ...]
    constraints: PlanConstraints
    prior_summary: str | None = None
    catalogue_snapshot_id: str | None = None
    occurrence: Literal["ENUMERATION", "DESCRIPTION", "SAFE_SQL"] | None = None


class PlannedTask(FrozenModel):
    local_id: str
    capability_id: str
    connector_id: str | None = None
    depends_on: tuple[str, ...] = ()
    inputs: dict[str, Any]
    rationale: str


class Plan(FrozenModel):
    phase: WorkflowState
    tasks: tuple[PlannedTask, ...]
    phase_exit_criteria: tuple[str, ...]
    assumptions: tuple[str, ...] = ()


class SelectRelevantAssetsInput(FrozenModel):
    requirement: RequirementSpec
    catalogue_snapshot_id: UUID
    catalogue_assets: tuple[AssetRef, ...]
    max_assets: int = Field(ge=1)


class SelectedAsset(FrozenModel):
    asset: AssetRef
    role: Literal["SOURCE", "REFERENCE", "LOOKUP"]
    reason: str
    confidence: float


class ExcludedAsset(FrozenModel):
    asset: AssetRef
    reason: str


class SelectRelevantAssetsOutput(FrozenModel):
    selected: tuple[SelectedAsset, ...]
    excluded_notable: tuple[ExcludedAsset, ...] = ()


class ExpectedColumn(FrozenModel):
    name: str
    type_hint: str


class GenerateSqlQueryInput(FrozenModel):
    requirement: RequirementSpec
    selected_assets: tuple[AssetRef, ...]
    dialect: str = "snowflake"
    target: AssetRef | None = None
    prior_attempt_feedback: tuple[str, ...] | None = None


class GenerateSqlQueryOutput(FrozenModel):
    sql: SqlText
    explanation: str
    expected_columns: tuple[ExpectedColumn, ...]
    expected_grain: tuple[str, ...] | None = None
    assumptions: tuple[str, ...] = ()


class QualityCheckResult(FrozenModel):
    check_id: str
    passed: bool
    detail: str


class ValidationReport(FrozenModel):
    passed: bool
    checks: tuple[QualityCheckResult, ...]
    row_count: int
    expected_columns: tuple[str, ...]
