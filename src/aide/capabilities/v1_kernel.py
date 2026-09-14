"""Minimal V1 capability catalogue needed to exercise DE 002A contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from aide.capabilities.io import (
    ClassifySqlInput,
    ClassifySqlOutput,
    CreateDatasetInput,
    CreateDatasetOutput,
    DescribeAssetInput,
    DescribeAssetOutput,
    DetectSchemaDriftInput,
    DetectSchemaDriftOutput,
    DiscoverAssetsInput,
    DiscoverAssetsOutput,
    DropDatasetInput,
    DropDatasetOutput,
    EmitWorkflowSummaryInput,
    EvaluateExecutionPolicyInput,
    EvaluateExecutionPolicyOutput,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    GenerateSqlQueryInput,
    GenerateSqlQueryOutput,
    GetCostMetricsOutput,
    GetExecutionMetricsOutput,
    InferRelationshipsInput,
    InferRelationshipsOutput,
    InterpretRequirementInput,
    MetricsQueryInput,
    ModelDesign,
    Plan,
    PlanPhaseInput,
    ProfileDatasetInput,
    ProfileDatasetOutput,
    ProposeModelDesignInput,
    RequirementSpec,
    SampleDatasetInput,
    SampleDatasetOutput,
    SelectRelevantAssetsInput,
    SelectRelevantAssetsOutput,
    ValidateQueryInput,
    ValidateQueryOutput,
    ValidateResultInput,
    ValidationReport,
    WorkflowSummary,
)
from aide.capabilities.registry import CapabilityRegistry
from aide.capabilities.spec import (
    CapabilitySpec,
    ConnectorRequirement,
    RetryPolicy,
)
from aide.domain.effects import EffectSemantics
from aide.domain.enums import ApprovalRule, RiskLevel
from aide.domain.failures import FailureClass
from aide.domain.permissions import PermissionLevel


class EmptyInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EmptyOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


_TRANSIENT = frozenset(
    {FailureClass.TRANSIENT_PROVIDER, FailureClass.CONNECTOR_FAILURE, FailureClass.TIMEOUT}
)


def _spec(
    capability_id: str,
    permission: PermissionLevel,
    *,
    kind: str = "deterministic",
    approval: ApprovalRule = ApprovalRule.NEVER,
    effect: EffectSemantics = EffectSemantics.SIDE_EFFECT_FREE,
    connector_mode: str = "REQUIRED",
    connector_kinds: frozenset[str] = frozenset({"warehouse"}),
    max_attempts: int = 2,
    risk: RiskLevel = RiskLevel.LOW,
    cost_class: str = "warehouse",
    input_schema: type[BaseModel] = EmptyInput,
    output_schema: type[BaseModel] = EmptyOutput,
    timeout_seconds: int = 60,
) -> CapabilitySpec:
    return CapabilitySpec(
        id=capability_id,
        version=1,
        kind=kind,  # type: ignore[arg-type]
        purpose=capability_id,
        input_schema=input_schema,
        output_schema=output_schema,
        input_schema_version=1,
        output_schema_version=1,
        required_permission=permission,
        risk=risk,
        approval=approval,
        timeout_seconds=timeout_seconds,
        retry=RetryPolicy(max_attempts=max_attempts, backoff="exp", retry_on=_TRANSIENT),
        failure_classes=_TRANSIENT,
        connector_requirement=ConnectorRequirement(mode=connector_mode, kinds=connector_kinds),  # type: ignore[arg-type]
        effect_semantics=effect,
        cost_class=cost_class,  # type: ignore[arg-type]
    )


KERNEL_CAPABILITIES: tuple[CapabilitySpec, ...] = (
    _spec(
        "discover_assets",
        PermissionLevel.READ,
        max_attempts=3,
        input_schema=DiscoverAssetsInput,
        output_schema=DiscoverAssetsOutput,
    ),
    _spec(
        "describe_asset",
        PermissionLevel.READ,
        input_schema=DescribeAssetInput,
        output_schema=DescribeAssetOutput,
    ),
    _spec(
        "detect_schema_drift",
        PermissionLevel.READ,
        input_schema=DetectSchemaDriftInput,
        output_schema=DetectSchemaDriftOutput,
    ),
    _spec(
        "profile_dataset",
        PermissionLevel.READ,
        input_schema=ProfileDatasetInput,
        output_schema=ProfileDatasetOutput,
    ),
    _spec(
        "sample_dataset",
        PermissionLevel.READ,
        risk=RiskLevel.MEDIUM,
        input_schema=SampleDatasetInput,
        output_schema=SampleDatasetOutput,
    ),
    _spec(
        "infer_relationships",
        PermissionLevel.READ,
        input_schema=InferRelationshipsInput,
        output_schema=InferRelationshipsOutput,
    ),
    _spec(
        "validate_query",
        PermissionLevel.READ,
        input_schema=ValidateQueryInput,
        output_schema=ValidateQueryOutput,
    ),
    _spec(
        "execute_query",
        PermissionLevel.READ,
        risk=RiskLevel.MEDIUM,
        input_schema=ExecuteQueryInput,
        output_schema=ExecuteQueryOutput,
    ),
    _spec(
        "get_execution_metrics",
        PermissionLevel.READ,
        input_schema=MetricsQueryInput,
        output_schema=GetExecutionMetricsOutput,
    ),
    _spec(
        "get_cost_metrics",
        PermissionLevel.READ,
        input_schema=MetricsQueryInput,
        output_schema=GetCostMetricsOutput,
    ),
    _spec(
        "create_dataset",
        PermissionLevel.DEVELOPMENT_WRITE,
        approval=ApprovalRule.IF_POLICY_FLAGS,
        effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        risk=RiskLevel.MEDIUM,
        input_schema=CreateDatasetInput,
        output_schema=CreateDatasetOutput,
    ),
    _spec(
        "drop_dataset",
        PermissionLevel.DESTRUCTIVE,
        approval=ApprovalRule.ALWAYS,
        effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        risk=RiskLevel.HIGH,
        input_schema=DropDatasetInput,
        output_schema=DropDatasetOutput,
    ),
    _spec(
        "classify_sql",
        PermissionLevel.READ,
        connector_mode="NONE",
        connector_kinds=frozenset(),
        max_attempts=1,
        cost_class="free",
        input_schema=ClassifySqlInput,
        output_schema=ClassifySqlOutput,
    ),
    _spec(
        "interpret_requirement",
        PermissionLevel.READ,
        kind="reasoning",
        connector_mode="NONE",
        connector_kinds=frozenset(),
        risk=RiskLevel.MEDIUM,
        cost_class="llm",
        input_schema=InterpretRequirementInput,
        output_schema=RequirementSpec,
    ),
    _spec(
        "plan_phase",
        PermissionLevel.READ,
        kind="reasoning",
        connector_mode="NONE",
        connector_kinds=frozenset(),
        risk=RiskLevel.MEDIUM,
        cost_class="llm",
        input_schema=PlanPhaseInput,
        output_schema=Plan,
    ),
    _spec(
        "select_relevant_assets",
        PermissionLevel.READ,
        kind="reasoning",
        connector_mode="NONE",
        connector_kinds=frozenset(),
        risk=RiskLevel.MEDIUM,
        cost_class="llm",
        input_schema=SelectRelevantAssetsInput,
        output_schema=SelectRelevantAssetsOutput,
    ),
    _spec(
        "generate_sql_query",
        PermissionLevel.READ,
        kind="reasoning",
        connector_mode="NONE",
        connector_kinds=frozenset(),
        risk=RiskLevel.MEDIUM,
        cost_class="llm",
        input_schema=GenerateSqlQueryInput,
        output_schema=GenerateSqlQueryOutput,
    ),
    _spec(
        "propose_model_design",
        PermissionLevel.READ,
        kind="reasoning",
        connector_mode="NONE",
        connector_kinds=frozenset(),
        risk=RiskLevel.MEDIUM,
        cost_class="llm",
        input_schema=ProposeModelDesignInput,
        output_schema=ModelDesign,
        timeout_seconds=180,
    ),
    _spec(
        "evaluate_execution_policy",
        PermissionLevel.READ,
        connector_mode="REQUIRED",
        connector_kinds=frozenset({"warehouse"}),
        max_attempts=1,
        cost_class="free",
        input_schema=EvaluateExecutionPolicyInput,
        output_schema=EvaluateExecutionPolicyOutput,
    ),
    _spec(
        "validate_result",
        PermissionLevel.READ,
        connector_mode="NONE",
        connector_kinds=frozenset(),
        max_attempts=1,
        cost_class="free",
        input_schema=ValidateResultInput,
        output_schema=ValidationReport,
    ),
    _spec(
        "emit_workflow_summary",
        PermissionLevel.READ,
        connector_mode="NONE",
        connector_kinds=frozenset(),
        max_attempts=1,
        cost_class="free",
        input_schema=EmitWorkflowSummaryInput,
        output_schema=WorkflowSummary,
    ),
    _spec(
        "prepare_git_change",
        PermissionLevel.GIT_WRITE,
        approval=ApprovalRule.IF_POLICY_FLAGS,
        effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        connector_kinds=frozenset({"vcs"}),
        risk=RiskLevel.MEDIUM,
        cost_class="external_api",
    ),
    _spec(
        "prepare_pull_request",
        PermissionLevel.GIT_WRITE,
        approval=ApprovalRule.IF_POLICY_FLAGS,
        effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        connector_kinds=frozenset({"vcs"}),
        risk=RiskLevel.MEDIUM,
        cost_class="external_api",
    ),
    _spec(
        "deploy_staging",
        PermissionLevel.STAGING_DEPLOY,
        approval=ApprovalRule.ALWAYS,
        effect=EffectSemantics.NON_IDEMPOTENT,
        connector_kinds=frozenset({"transformation", "orchestration"}),
        max_attempts=1,
        risk=RiskLevel.HIGH,
        cost_class="warehouse",
    ),
)


def kernel_registry() -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for spec in KERNEL_CAPABILITIES:
        registry.register(spec)
    return registry
