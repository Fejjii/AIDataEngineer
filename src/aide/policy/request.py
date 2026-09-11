"""Policy request and decision contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.capabilities.spec import CapabilitySpec
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.spec import ConnectorSpec
from aide.domain.approvals import ApprovalRecord, ApprovalSubject
from aide.domain.artifacts import ArtifactProvenance
from aide.domain.costs import CostEstimate
from aide.domain.enums import TargetEnv
from aide.domain.git import GitChangeClassification
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef
from aide.domain.sql import SqlClassification
from aide.policy.reasons import Decision, DenyClass, ReasonCode, Routing


class PolicyRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    contract_snapshot_id: UUID
    principal: PrincipalRef
    grant_authorization: GrantAuthorization
    capability: CapabilitySpec
    connector: ConnectorSpec | None
    connector_health: ConnectorHealthSnapshot | None
    target_environment: TargetEnv | None
    workflow_grants: frozenset[PermissionLevel]
    payload_classification: SqlClassification | GitChangeClassification | None = None
    estimated_cost: CostEstimate | None = None
    artifact_provenance: tuple[ArtifactProvenance, ...] = ()
    approvals: tuple[ApprovalRecord, ...] = ()
    evaluated_at: datetime
    capability_known: bool = True
    connector_registered: bool = True
    connector_advertises_capability: bool = True
    drop_target_created_by_workflow: bool | None = None
    create_dataset_replace_unowned: bool = False
    design_approval_required: bool = False
    design_subject: ApprovalSubject | None = None
    dev_namespace_schemas: frozenset[tuple[str, str]] = frozenset()


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["ALLOW", "REQUIRE_APPROVAL", "DENY"]
    reasons: tuple[ReasonCode, ...]
    deny_class: Literal["ENVIRONMENTAL", "SCOPE", "SECURITY"] | None
    routing: Literal["EXECUTE", "APPROVAL", "PARK", "FAIL_CLOSED"]
    required_permission: PermissionLevel
    approval_requirements: tuple[ApprovalSubject, ...]
    evaluated_rules: tuple[str, ...]
    decided_at: datetime

    @property
    def decision_enum(self) -> Decision:
        return Decision(self.decision)

    @property
    def deny_class_enum(self) -> DenyClass | None:
        return DenyClass(self.deny_class) if self.deny_class else None

    @property
    def routing_enum(self) -> Routing:
        return Routing(self.routing)
