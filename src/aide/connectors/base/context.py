"""Call and recovery context contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.enums import TargetEnv
from aide.domain.versions import CapabilityContractRef


class RedactionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    redact_secrets: bool = True
    max_excerpt_chars: int = Field(default=512, ge=0)


class CallContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    contract_snapshot_id: UUID
    attempt_id: UUID
    attempt_number: int = Field(ge=1)
    claim_epoch: int = Field(ge=1)
    cancellation_epoch: int = Field(ge=0)
    deadline: datetime
    external_correlation: str
    redaction: RedactionPolicy = Field(default_factory=RedactionPolicy)


class AttemptRecoveryRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempt_id: UUID
    attempt_number: int = Field(ge=1)
    external_ref: str | None = None
    query_id: str | None = None
    release_id: str | None = None
    commit_sha: str | None = None


class RecoveryContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(min_length=64, max_length=64)
    resolved_input_schema_version: int = Field(ge=1)
    capability: CapabilityContractRef
    connector_id: str
    connector_version: str
    target_environment: TargetEnv
    attempts: tuple[AttemptRecoveryRef, ...]
    operation_locator: dict[str, str] = Field(default_factory=dict)
    reconcile_deadline: datetime
