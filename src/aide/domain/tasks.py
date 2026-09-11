"""Task templates, materialized tasks, attempts, and phase-run identity."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from aide.domain.enums import RiskLevel, TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.identity import (
    UnresolvedInputError,
    compute_operation_idempotency_key,
    compute_resolved_input_digest,
    contains_unresolved_placeholder,
)
from aide.domain.permissions import PermissionLevel
from aide.domain.states import (
    AttemptOutcome,
    DispatchState,
    PhaseRunStatus,
    TaskState,
    WorkflowState,
)


class PhaseRunIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_run_id: UUID
    workflow_id: UUID
    phase: WorkflowState
    generation: int = Field(ge=1)
    contract_snapshot_id: UUID
    status: PhaseRunStatus


class TaskTemplate(BaseModel):
    """Immutable template. Has no operation identity and cannot be claimed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    template_id: UUID
    phase_run_id: UUID
    local_id: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    capability_contract_version: int = Field(ge=1)
    connector_id: str | None = None
    depends_on: tuple[str, ...] = ()
    unresolved_inputs: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(ge=1)
    max_attempts: int = Field(ge=1)

    @model_validator(mode="after")
    def _forbid_operation_fields(self) -> TaskTemplate:
        extra = set(self.model_dump()) & {
            "operation_idempotency_key",
            "resolved_input_digest",
            "attempt_number",
        }
        if extra:
            raise ValueError(f"task templates cannot carry {sorted(extra)}")
        return self


class MaterializedTask(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    template_id: UUID
    workflow_id: UUID
    phase_run_id: UUID
    local_id: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    capability_contract_version: int = Field(ge=1)
    input_schema_version: int = Field(ge=1)
    output_schema_version: int = Field(ge=1)
    connector_id: str | None
    connector_version: str | None
    target_environment: TargetEnv | None
    resolved_inputs: dict[str, Any]
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    required_permission: PermissionLevel
    risk: RiskLevel
    timeout_seconds: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    validators: tuple[str, ...] = ()
    status: TaskState = TaskState.MATERIALIZED

    @model_validator(mode="after")
    def _require_resolved_identity(self) -> MaterializedTask:
        if contains_unresolved_placeholder(self.resolved_inputs):
            raise UnresolvedInputError(
                "materialized tasks cannot contain unresolved $from placeholders"
            )
        expected = compute_operation_idempotency_key(
            workflow_id=self.workflow_id,
            phase_run_id=self.phase_run_id,
            local_id=self.local_id,
            capability_id=self.capability_id,
            capability_contract_version=self.capability_contract_version,
            connector_id=self.connector_id,
            connector_version=self.connector_version,
            target_environment=self.target_environment,
            resolved_input_digest=self.resolved_input_digest,
        )
        if self.operation_idempotency_key != expected:
            raise ValueError("operation_idempotency_key does not match canonical identity")
        return self


class TaskAttempt(BaseModel):
    """Append-only attempt. Identity never contributes to the operation key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: UUID
    task_id: UUID
    phase_run_id: UUID
    attempt_number: int = Field(ge=1)
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    lease_owner: str
    claim_epoch: int = Field(ge=1)
    cancellation_epoch: int = Field(ge=0)
    started_at: datetime
    last_heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    dispatch_state: DispatchState
    outcome: AttemptOutcome
    external_ref: str | None = None
    failure_classification: FailureClass | None = None


def materialize_task(
    template: TaskTemplate,
    *,
    task_id: UUID,
    workflow_id: UUID,
    resolved_inputs: BaseModel | dict[str, Any],
    input_schema: type[BaseModel],
    input_schema_version: int,
    output_schema_version: int,
    connector_id: str | None,
    connector_version: str | None,
    target_environment: TargetEnv | None,
    required_permission: PermissionLevel,
    risk: RiskLevel,
    validators: tuple[str, ...] = (),
) -> MaterializedTask:
    """Resolve, validate, digest, then compute operation identity atomically."""
    raw_payload: object
    if isinstance(resolved_inputs, BaseModel):
        raw_payload = resolved_inputs.model_dump(mode="json")
    else:
        raw_payload = resolved_inputs
    if contains_unresolved_placeholder(raw_payload):
        raise UnresolvedInputError(
            "cannot materialize operation identity before resolved validated input exists"
        )
    if isinstance(resolved_inputs, BaseModel):
        if not isinstance(resolved_inputs, input_schema):
            raise UnresolvedInputError(f"resolved inputs must validate as {input_schema.__name__}")
        payload = resolved_inputs.model_dump(mode="json")
        digest_source: BaseModel | dict[str, Any] = resolved_inputs
    else:
        try:
            validated = input_schema.model_validate(resolved_inputs)
        except ValidationError as exc:
            raise UnresolvedInputError(
                "cannot materialize operation identity before resolved validated input exists"
            ) from exc
        payload = validated.model_dump(mode="json")
        digest_source = validated
    if contains_unresolved_placeholder(payload):
        raise UnresolvedInputError(
            "cannot materialize operation identity before resolved validated input exists"
        )
    digest = compute_resolved_input_digest(digest_source)
    key = compute_operation_idempotency_key(
        workflow_id=workflow_id,
        phase_run_id=template.phase_run_id,
        local_id=template.local_id,
        capability_id=template.capability_id,
        capability_contract_version=template.capability_contract_version,
        connector_id=connector_id,
        connector_version=connector_version,
        target_environment=target_environment,
        resolved_input_digest=digest,
    )
    return MaterializedTask(
        task_id=task_id,
        template_id=template.template_id,
        workflow_id=workflow_id,
        phase_run_id=template.phase_run_id,
        local_id=template.local_id,
        capability_id=template.capability_id,
        capability_contract_version=template.capability_contract_version,
        input_schema_version=input_schema_version,
        output_schema_version=output_schema_version,
        connector_id=connector_id,
        connector_version=connector_version,
        target_environment=target_environment,
        resolved_inputs=payload,
        resolved_input_digest=digest,
        operation_idempotency_key=key,
        required_permission=required_permission,
        risk=risk,
        timeout_seconds=template.timeout_seconds,
        max_attempts=template.max_attempts,
        validators=validators,
    )
