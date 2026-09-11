"""Versioned CapabilitySpec contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.effects import EffectSemantics
from aide.domain.enums import ApprovalRule, RiskLevel
from aide.domain.failures import FailureClass
from aide.domain.permissions import PermissionLevel

CapabilityId = str
CapabilityKind = Literal["deterministic", "reasoning", "control"]
CostClass = Literal["free", "warehouse", "llm", "external_api"]


class RetryPolicy(BaseModel):
    """``max_attempts`` includes the initial attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_attempts: int = Field(ge=1)
    backoff: Literal["none", "fixed", "exp"] = "none"
    retry_on: frozenset[FailureClass] = frozenset()


class ConnectorRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["NONE", "REQUIRED", "OPTIONAL"]
    kinds: frozenset[str] = frozenset()

    @property
    def required(self) -> bool:
        return self.mode == "REQUIRED"


class AuditSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    record_input_fields: tuple[str, ...] = ()
    record_output_fields: tuple[str, ...] = ()
    redact_fields: tuple[str, ...] = ()


class CapabilitySpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    id: CapabilityId
    version: int = Field(ge=1)
    kind: CapabilityKind
    purpose: str = Field(min_length=1)
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    input_schema_version: int = Field(ge=1)
    output_schema_version: int = Field(ge=1)
    required_permission: PermissionLevel
    risk: RiskLevel
    approval: ApprovalRule
    timeout_seconds: int = Field(ge=1)
    retry: RetryPolicy
    failure_classes: frozenset[FailureClass]
    validators: tuple[str, ...] = ()
    audit: AuditSpec = Field(default_factory=AuditSpec)
    connector_requirement: ConnectorRequirement
    effect_semantics: EffectSemantics
    cost_class: CostClass
