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


class DropDatasetInput(FrozenModel):
    target: AssetRef
    created_by_workflow: UUID


class DropDatasetOutput(FrozenModel):
    dropped: bool


class DetectSchemaDriftInput(FrozenModel):
    asset: AssetRef
    baseline_snapshot_id: UUID
    baseline_columns: tuple[ColumnSpec, ...] | None = None


class ColumnTypeChange(FrozenModel):
    name: str
    from_type: str
    to_type: str


class RenamedColumnCandidate(FrozenModel):
    from_name: str
    to_name: str
    confidence: float = Field(ge=0, le=1)


class DetectSchemaDriftOutput(FrozenModel):
    drifted: bool
    added: tuple[ColumnSpec, ...]
    removed: tuple[ColumnSpec, ...]
    type_changed: tuple[ColumnTypeChange, ...]
    renamed_candidates: tuple[RenamedColumnCandidate, ...]


class TopValue(FrozenModel):
    value_masked: str | None
    count: int = Field(ge=0)


class ProfileColumn(FrozenModel):
    name: str
    null_ratio: float = Field(ge=0, le=1)
    distinct_ratio: float = Field(ge=0, le=1)
    min: Any | None = None
    max: Any | None = None
    mean: float | None = None
    top_values: tuple[TopValue, ...] = ()
    inferred_semantic: Literal["ID", "DATE", "AMOUNT", "CODE", "TEXT", "FLAG"] | None = None


class CandidateKey(FrozenModel):
    columns: tuple[str, ...]
    uniqueness_ratio: float = Field(ge=0, le=1)


class ProfileDatasetInput(FrozenModel):
    asset: AssetRef
    columns: tuple[str, ...] | None = None
    budget: Budget
    sample_fraction: float | None = Field(default=None, ge=0, le=1)
    top_k: int = Field(default=10, ge=1)


class ProfileDatasetOutput(FrozenModel):
    asset: AssetRef
    row_count: int
    sampled: bool
    columns: tuple[ProfileColumn, ...]
    candidate_keys: tuple[CandidateKey, ...]
    duplicate_groups_estimate: int
    profile_id: UUID


class SampleDatasetInput(FrozenModel):
    asset: AssetRef
    columns: tuple[str, ...] | None = None
    n: int = Field(ge=1, le=20)
    where: SqlText | None = None


class SampleDatasetOutput(FrozenModel):
    rows: tuple[dict[str, Any], ...]
    masked_columns: tuple[str, ...]
    sample_id: UUID


class InferRelationshipsInput(FrozenModel):
    assets: tuple[AssetRef, ...]
    profiles: tuple[UUID, ...] = ()
    max_pairs: int = Field(ge=1)
    budget: Budget


class RelationshipCandidate(FrozenModel):
    from_asset: AssetRef
    from_columns: tuple[str, ...]
    to_asset: AssetRef
    to_columns: tuple[str, ...]
    inclusion_ratio: float = Field(ge=0, le=1)
    cardinality: Literal["1:1", "1:N", "N:M"]
    confidence: float = Field(ge=0, le=1)


class InferRelationshipsOutput(FrozenModel):
    candidates: tuple[RelationshipCandidate, ...]
    relationships_id: UUID


class MetricsQueryInput(FrozenModel):
    query_tag: str
    since: datetime


class QueryMetric(FrozenModel):
    query_id: str
    duration_ms: int
    bytes_scanned: int | None = None
    rows_produced: int | None = None
    partitions_scanned: int | None = None
    partitions_total: int | None = None
    spilled_bytes: int | None = None
    warehouse: str | None = None


class GetExecutionMetricsOutput(FrozenModel):
    queries: tuple[QueryMetric, ...]
    as_of: datetime | None = None
    complete: bool = True


class TaskCostBreakdown(FrozenModel):
    task_id: str
    credits_used: float


class GetCostMetricsOutput(FrozenModel):
    credits_used: float
    estimated_cost: float
    currency: str = "USD"
    breakdown_by_task: tuple[TaskCostBreakdown, ...] = ()
    as_of: datetime | None = None
    complete: bool = False


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
    occurrence: Literal["ENUMERATION", "DESCRIPTION", "SAFE_SQL", "DELIVERY"] | None = None
    catalogue_assets: tuple[AssetRef, ...] = ()


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


class EvaluateExecutionPolicyInput(FrozenModel):
    target_capability_id: str
    connector_id: str
    sql: SqlText


class EvaluateExecutionPolicyOutput(FrozenModel):
    decision: str
    routing: str
    reasons: tuple[str, ...] = ()


class ValidateResultInput(FrozenModel):
    row_count: int
    rows: tuple[dict[str, Any], ...] | None
    expected_columns: tuple[ExpectedColumn, ...]


class WorkflowSummary(FrozenModel):
    outcome: Literal["DELIVERED_STAGING", "DELIVERED_PR_ONLY", "NO_DELIVERY"]
    workflow_id: UUID
    validation_passed: bool
    row_count: int
    sql_dialect: str | None = None


class EmitWorkflowSummaryInput(FrozenModel):
    outcome: Literal["DELIVERED_STAGING", "DELIVERED_PR_ONLY", "NO_DELIVERY"] = "NO_DELIVERY"
    validation_passed: bool
    row_count: int
    sql_dialect: str | None = None


DeliverableType = Literal[
    "ANALYTICAL_DATA_PRODUCT",
    "PIPELINE",
    "MODEL_CHANGE",
    "QUALITY_SUITE",
    "INVESTIGATION",
    "UNKNOWN",
]
HistoryRequirement = Literal["NONE", "CURRENT_ONLY", "FULL_HISTORY", "UNKNOWN"]
AuditabilitySignal = Literal["LOW", "HIGH", "UNKNOWN"]
SourceStructure = Literal["NORMALIZED_3NF", "DENORMALIZED_EXTRACT", "EVENT_LOG", "MIXED", "UNKNOWN"]
VolumeClass = Literal["S", "M", "L", "XL", "UNKNOWN"]
VelocityClass = Literal["BATCH_DAILY", "INTRA_DAY", "NEAR_REAL_TIME", "UNKNOWN"]
ChangeFrequency = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
QueryPattern = Literal[
    "AGGREGATE_BI",
    "DRILL_DOWN",
    "OPERATIONAL_LOOKUP",
    "ML_FEATURES",
    "UNKNOWN",
]
DownstreamConsumer = Literal["BI", "ANALYSTS_SQL", "ML", "APPLICATION", "UNKNOWN"]
LatencyRequirement = Literal["DAILY", "HOURLY", "MINUTES", "UNKNOWN"]
CostSensitivity = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
KeyQuality = Literal["CLEAN", "DUPLICATES_PRESENT", "NO_NATURAL_KEY", "UNKNOWN"]
IdentifierAlignment = Literal["ALIGNED", "PARTIAL", "MISALIGNED", "UNKNOWN"]
TernaryFlag = Literal["TRUE", "FALSE", "UNKNOWN"]
NamingConvention = Literal["DBT_DEFAULT", "MEDALLION"]
LayeringClass = Literal[
    "STAGING_INTERMEDIATE_MARTS",
    "REUSE_EXISTING",
    "TESTS_ONLY",
    "EPHEMERAL_QUERIES",
]
IntegrationClass = Literal["NO_VAULT", "RAW_VAULT_RECOMMENDED"]
PresentationClass = Literal[
    "STAR_SCHEMA",
    "WIDE_FEATURE_TABLE",
    "NORMALIZED_SERVING",
    "SNOWFLAKE_SCHEMA",
]
FactKind = Literal["TRANSACTION_FACT", "PERIODIC_SNAPSHOT_FACT", "ACCUMULATING_SNAPSHOT_FACT"]
HistoryClass = Literal["SCD1", "SCD2", "STATIC"]
HistoryStrategy = Literal[
    "snapshot_timestamp",
    "snapshot_check",
    "source_validity_intervals",
    "static",
    "none",
]
MaterializationKind = Literal[
    "view", "table", "ephemeral", "incremental", "snapshot", "dynamic_table"
]
ModelKind = Literal[
    "STAGING",
    "INTERMEDIATE",
    "DIMENSION",
    "FACT",
    "MART",
    "SNAPSHOT",
    "HUB",
    "LINK",
    "SATELLITE",
]
ModelLayer = Literal["staging", "intermediate", "marts"]


class PlatformCapabilities(FrozenModel):
    supports_merge: TernaryFlag = "UNKNOWN"
    supports_clustering: TernaryFlag = "UNKNOWN"
    supports_time_travel: TernaryFlag = "UNKNOWN"
    supports_streams_tasks: TernaryFlag = "UNKNOWN"
    supports_dynamic_tables: TernaryFlag = "UNKNOWN"


class EntityHistorySignal(FrozenModel):
    entity: str
    asset: AssetRef | None = None
    has_source_history: TernaryFlag = "UNKNOWN"
    validity_columns: tuple[str, ...] = ()


class DuplicateGrainEvidence(FrozenModel):
    entity: str
    asset: AssetRef | None = None
    columns: tuple[str, ...]
    uniqueness_ratio: float | None = None
    duplicate_groups_estimate: int = Field(ge=0, default=0)
    extra_row_estimate: int = Field(ge=0, default=0)
    reason: str


class ModellingSignals(FrozenModel):
    deliverable_type: DeliverableType
    history_requirements: HistoryRequirement
    auditability: AuditabilitySignal
    source_count: int | None = None
    source_system_count: int | None = None
    source_structure: SourceStructure = "UNKNOWN"
    volume_class: VolumeClass = "UNKNOWN"
    volume_row_count: int | None = None
    velocity: VelocityClass = "UNKNOWN"
    change_frequency: ChangeFrequency = "UNKNOWN"
    entity_history_in_source: TernaryFlag = "UNKNOWN"
    entity_history: tuple[EntityHistorySignal, ...] = ()
    query_patterns: tuple[QueryPattern, ...] = ("UNKNOWN",)
    downstream_consumers: tuple[DownstreamConsumer, ...] = ("UNKNOWN",)
    latency_requirement: LatencyRequirement = "UNKNOWN"
    platform_capabilities: PlatformCapabilities = Field(default_factory=PlatformCapabilities)
    cost_sensitivity: CostSensitivity = "UNKNOWN"
    key_quality: KeyQuality = "UNKNOWN"
    identifier_alignment: IdentifierAlignment = "UNKNOWN"
    identifier_alignment_ratio: float | None = None
    duplicate_grains: tuple[DuplicateGrainEvidence, ...] = ()
    unknown_reasons: tuple[str, ...] = ()


class ModellingOpenQuestion(FrozenModel):
    topic: str
    question: str
    blocking: bool = False
    rule: str | None = None


class LayeringDecision(FrozenModel):
    decision: LayeringClass
    rule: Literal["L1", "L2", "L3", "L4"]
    naming: NamingConvention = "DBT_DEFAULT"


class IntegrationLayerDecision(FrozenModel):
    decision: IntegrationClass
    rule: Literal["V1", "V2", "V3"]
    recommendation: str | None = None


class PresentationDecision(FrozenModel):
    decision: PresentationClass
    rule: Literal["P1", "P2", "P3", "P4", "P5"]
    dimension: str | None = None


class FactDecision(FrozenModel):
    entity: str
    kind: FactKind
    grain: tuple[str, ...]
    source_assets: tuple[AssetRef, ...] = ()
    materialization: MaterializationKind
    unique_key: tuple[str, ...] = ()
    watermark_column: str | None = None
    watermark_lookback_days: int | None = None
    dedup_required: bool = False
    dedup_rule: str | None = None
    rule: tuple[str, ...] = ()


class DimensionDecision(FrozenModel):
    entity: str
    history: HistoryClass
    source_history: bool
    strategy: HistoryStrategy
    source_assets: tuple[AssetRef, ...] = ()
    tracked_columns: tuple[str, ...] = ()
    hybrid_scd1_attributes: tuple[str, ...] = ()
    rule: tuple[str, ...] = ()


class DedupDecision(FrozenModel):
    entity: str
    grain: tuple[str, ...]
    description: str
    rule: Literal["F4"] = "F4"


class MaterializationDecision(FrozenModel):
    target: str
    materialization: MaterializationKind
    rule: Literal["M1", "M2", "M3", "M4", "M5", "M6", "M7"]
    detail: str


class ArchitectureDecision(FrozenModel):
    signals: ModellingSignals
    layering: LayeringDecision
    naming: NamingConvention
    integration_layer: IntegrationLayerDecision
    presentation: PresentationDecision
    facts: tuple[FactDecision, ...]
    dimensions: tuple[DimensionDecision, ...]
    dedup: tuple[DedupDecision, ...] = ()
    materialization: tuple[MaterializationDecision, ...]
    recommendations: tuple[str, ...] = ()
    open_questions: tuple[ModellingOpenQuestion, ...] = ()
    approval_required: bool
    approval_reasons: tuple[str, ...] = ()
    rule_ids: tuple[str, ...]
    estimated_model_count: int = Field(ge=0)
    estimated_cost_class: VolumeClass = "UNKNOWN"


class AssetProfileEvidence(FrozenModel):
    asset: AssetRef
    row_count: int
    columns: tuple[str, ...]
    column_types: tuple[tuple[str, str], ...] = ()
    candidate_keys: tuple[CandidateKey, ...] = ()
    key_uniqueness: tuple[tuple[str, float], ...] = ()
    composite_key_uniqueness: tuple[tuple[tuple[str, ...], float, bool], ...] = ()
    duplicate_groups_estimate: int = Field(ge=0, default=0)
    has_valid_from: bool = False
    has_valid_to: bool = False
    has_updated_at: bool = False
    has_created_at: bool = False
    has_loaded_at: bool = False
    updated_at_null_ratio: float | None = None
    loaded_at_null_ratio: float | None = None
    foreign_key_columns: tuple[str, ...] = ()


class DuplicateEvidenceLite(FrozenModel):
    asset: AssetRef
    columns: tuple[str, ...]
    uniqueness_ratio: float
    duplicate_groups_estimate: int = Field(ge=0)
    extra_row_estimate: int = Field(ge=0)
    reason: str


class ProfilingEvidenceSummary(FrozenModel):
    fixture_version: str | None = None
    fact_ids: tuple[str, ...] = ()
    fact_details: tuple[tuple[str, str], ...] = ()
    relationship_count: int = 0
    masking_applied: bool = True


class DedupRule(FrozenModel):
    partition: tuple[str, ...]
    order_by: tuple[str, ...]
    keep: Literal["first"] = "first"
    description: str
    assumption: bool = True


class IncrementalConfig(FrozenModel):
    strategy: Literal["merge", "append", "delete+insert"]
    unique_key: tuple[str, ...]
    watermark_column: str
    lookback_days: int = Field(ge=0, default=3)


class ModelColumn(FrozenModel):
    name: str
    expression: str | None = None
    data_type: str | None = None
    tests: tuple[str, ...] = ()
    source_asset: AssetRef | None = None
    source_column: str | None = None
    is_pii: bool = False
    pii_handling: Literal["masked", "excluded", "hashed"] | None = None
    description: str | None = None


class ModelDesignUnit(FrozenModel):
    name: str
    model_kind: ModelKind
    layer: ModelLayer
    source_assets: tuple[AssetRef, ...] = ()
    grain: tuple[str, ...] = ()
    columns: tuple[ModelColumn, ...] = ()
    materialization: MaterializationKind
    unique_key: tuple[str, ...] = ()
    watermark: str | None = None
    incremental: IncrementalConfig | None = None
    dedup_rule: DedupRule | None = None
    history_strategy: HistoryStrategy | None = None
    tracked_scd2_columns: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    rule_refs: tuple[str, ...] = ()
    surrogate_key: str | None = None
    natural_keys: tuple[str, ...] = ()
    scd_type: HistoryClass | None = None


class ModelDesign(FrozenModel):
    layers: tuple[str, ...]
    models: tuple[ModelDesignUnit, ...]
    relationships: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    open_questions: tuple[ModellingOpenQuestion, ...] = ()
    assumptions: tuple[str, ...] = ()
    architecture_decision_digest: str = Field(min_length=64, max_length=64)


class DesignViolation(FrozenModel):
    code: str
    message: str
    model_name: str | None = None
    details: tuple[str, ...] = ()


class DesignValidationReport(FrozenModel):
    passed: bool
    violations: tuple[DesignViolation, ...]
    required_models_present: tuple[str, ...] = ()
    checked_rule_refs: tuple[str, ...] = ()


class ProposeModelDesignInput(FrozenModel):
    requirement: RequirementSpec
    architecture_decision: ArchitectureDecision
    selected_assets: tuple[AssetRef, ...]
    profiling_summary: ProfilingEvidenceSummary
    profile_evidence: tuple[AssetProfileEvidence, ...]
    relationship_evidence: tuple[RelationshipCandidate, ...]
    duplicate_evidence: tuple[DuplicateEvidenceLite, ...] = ()
