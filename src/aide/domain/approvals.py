"""Typed approval subjects. Matching uses the full binding; no permission on design."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aide.domain.costs import BudgetScope, CostUnit
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class OperationBinding(BaseModel):
    """Complete operation subject binding rechecked at decision and attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    artifact_hashes: tuple[str, ...]
    capability_id: str = Field(min_length=1)
    capability_contract_version: int = Field(ge=1)
    connector_id: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    target_environment: TargetEnv
    required_permission: PermissionLevel
    external_state_digest: str | None = None


class OperationApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["OPERATION"] = "OPERATION"
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    artifact_hashes: tuple[str, ...]
    capability_id: str = Field(min_length=1)
    capability_contract_version: int = Field(ge=1)
    connector_id: str = Field(min_length=1)
    connector_version: str = Field(min_length=1)
    target_environment: TargetEnv
    required_permission: PermissionLevel
    external_state_digest: str | None = None
    expires_at: datetime

    def as_binding(self) -> OperationBinding:
        return OperationBinding(
            operation_idempotency_key=self.operation_idempotency_key,
            resolved_input_digest=self.resolved_input_digest,
            artifact_hashes=self.artifact_hashes,
            capability_id=self.capability_id,
            capability_contract_version=self.capability_contract_version,
            connector_id=self.connector_id,
            connector_version=self.connector_version,
            target_environment=self.target_environment,
            required_permission=self.required_permission,
            external_state_digest=self.external_state_digest,
        )

    def covers_operation(self, binding: OperationBinding) -> bool:
        return self.as_binding() == binding


class DesignApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["DESIGN"] = "DESIGN"
    design_artifact_hash: str = Field(min_length=1)
    validation_report_hash: str = Field(min_length=1)
    invariant_hashes: tuple[str, ...]
    expires_at: datetime


class BudgetIncreaseApproval(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["BUDGET_INCREASE"] = "BUDGET_INCREASE"
    budget_scope: BudgetScope
    ledger_version: int = Field(ge=0)
    unit: CostUnit
    prior_cap: Decimal
    authorized_new_cap: Decimal
    authorized_delta: Decimal
    expires_at: datetime

    @model_validator(mode="after")
    def _delta_matches_caps(self) -> BudgetIncreaseApproval:
        if self.authorized_delta != self.authorized_new_cap - self.prior_cap:
            raise ValueError("authorized_delta must equal authorized_new_cap - prior_cap")
        return self


ApprovalSubject = Annotated[
    OperationApproval | DesignApproval | BudgetIncreaseApproval,
    Field(discriminator="kind"),
]


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: UUID
    workflow_id: UUID
    subject: ApprovalSubject
    subject_digest: str = Field(min_length=1)
    requester: PrincipalRef
    status: ApprovalStatus
    created_at: datetime
    expires_at: datetime
    decided_by: PrincipalRef | None = None
    decided_at: datetime | None = None
    comment: str | None = None
