"""Minimal V1 capability catalogue needed to exercise DE 002A contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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
) -> CapabilitySpec:
    return CapabilitySpec(
        id=capability_id,
        version=1,
        kind=kind,  # type: ignore[arg-type]
        purpose=capability_id,
        input_schema=EmptyInput,
        output_schema=EmptyOutput,
        input_schema_version=1,
        output_schema_version=1,
        required_permission=permission,
        risk=risk,
        approval=approval,
        timeout_seconds=60,
        retry=RetryPolicy(max_attempts=max_attempts, backoff="exp", retry_on=_TRANSIENT),
        failure_classes=_TRANSIENT,
        connector_requirement=ConnectorRequirement(mode=connector_mode, kinds=connector_kinds),  # type: ignore[arg-type]
        effect_semantics=effect,
        cost_class=cost_class,  # type: ignore[arg-type]
    )


KERNEL_CAPABILITIES: tuple[CapabilitySpec, ...] = (
    _spec("discover_assets", PermissionLevel.READ, max_attempts=3),
    _spec("describe_asset", PermissionLevel.READ),
    _spec("detect_schema_drift", PermissionLevel.READ),
    _spec("profile_dataset", PermissionLevel.READ),
    _spec("sample_dataset", PermissionLevel.READ, risk=RiskLevel.MEDIUM),
    _spec("infer_relationships", PermissionLevel.READ),
    _spec("validate_query", PermissionLevel.READ),
    _spec("execute_query", PermissionLevel.READ, risk=RiskLevel.MEDIUM),
    _spec("get_execution_metrics", PermissionLevel.READ),
    _spec("get_cost_metrics", PermissionLevel.READ),
    _spec(
        "create_dataset",
        PermissionLevel.DEVELOPMENT_WRITE,
        approval=ApprovalRule.IF_POLICY_FLAGS,
        effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        risk=RiskLevel.MEDIUM,
    ),
    _spec(
        "drop_dataset",
        PermissionLevel.DESTRUCTIVE,
        approval=ApprovalRule.ALWAYS,
        effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        risk=RiskLevel.HIGH,
    ),
    _spec(
        "classify_sql",
        PermissionLevel.READ,
        connector_mode="NONE",
        connector_kinds=frozenset(),
        max_attempts=1,
        cost_class="free",
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
