"""Typed Interview MVP repair contracts. Domain-only: no connectors or gateway."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.artifacts import ExecutionMode
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetRef
from aide.domain.twin import SHA256_PATTERN, SourceAuthorityRef

ACCEPTED_FAILURE_CLASS = FailureClass.SCHEMA_MISMATCH
ACCEPTED_ASSET_ADDRESS: tuple[str, str, str] = ("VANTARA_RAW", "BILLING", "INVOICES")
ACCEPTED_FROM_COLUMN = "INVOICE_STATUS"
ACCEPTED_TO_COLUMN = "STATUS"
ACCEPTED_ARTIFACT_PATH = "models/staging/stg_billing__invoices.sql"
ACCEPTED_AUTHORITY_ID = "snowflake_ro"

MAX_CONNECTOR_ATTEMPTS = 2
MAX_REPAIR_PROPOSALS = 2
MAX_APPLIED_REPAIRS_PER_TASK = 1
MAX_APPLIED_REPAIRS_PER_WORKFLOW = 1
MAX_POST_REPAIR_REVALIDATIONS = 1
MAX_RECURSIVE_REPAIRS = 0


class RepairModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RepairBlockReason(str, Enum):
    WRONG_TABLE = "WRONG_TABLE"
    WRONG_SOURCE = "WRONG_SOURCE"
    DIFFERENT_COLUMN_RENAME = "DIFFERENT_COLUMN_RENAME"
    DIFFERENT_NORMALIZED_TYPE = "DIFFERENT_NORMALIZED_TYPE"
    PREIMAGE_HASH_MISMATCH = "PREIMAGE_HASH_MISMATCH"
    JOIN_CHANGED = "JOIN_CHANGED"
    FILTER_CHANGED = "FILTER_CHANGED"
    GROUPING_CHANGED = "GROUPING_CHANGED"
    GRAIN_CHANGED = "GRAIN_CHANGED"
    MATERIALIZATION_CHANGED = "MATERIALIZATION_CHANGED"
    MACRO_CHANGED = "MACRO_CHANGED"
    YAML_CHANGED = "YAML_CHANGED"
    TEST_WEAKENED = "TEST_WEAKENED"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    TARGET_CHANGED = "TARGET_CHANGED"
    SOURCE_DATA_MUTATED = "SOURCE_DATA_MUTATED"
    SECOND_REPAIR = "SECOND_REPAIR"
    RECURSIVE_REPAIR = "RECURSIVE_REPAIR"
    MISSING_DRIFT_EVIDENCE = "MISSING_DRIFT_EVIDENCE"
    STALE_DRIFT_EVIDENCE = "STALE_DRIFT_EVIDENCE"
    NON_AUTHORITATIVE_DRIFT = "NON_AUTHORITATIVE_DRIFT"
    BROADER_PARSED_DIFF = "BROADER_PARSED_DIFF"
    STATIC_VALIDATION_FAILED = "STATIC_VALIDATION_FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    FAILURE_CLASS_NOT_ALLOWED = "FAILURE_CLASS_NOT_ALLOWED"


class DriftColumn(RepairModel):
    name: str = Field(min_length=1)
    data_type: str = Field(min_length=1)
    nullable: bool = True
    ordinal: int = Field(default=0, ge=0)


class DriftEvidence(RepairModel):
    observation_id: UUID
    evidence_ref_id: UUID
    asset: AssetRef
    from_column: str
    to_column: str
    old_data_type: str
    new_data_type: str
    drifted: bool
    added: tuple[DriftColumn, ...]
    removed: tuple[DriftColumn, ...]
    type_changed: tuple[tuple[str, str, str], ...] = ()
    observed_at: datetime
    fresh_until: datetime | None = None
    source_authority: SourceAuthorityRef
    authoritative: bool
    sha256: str = Field(pattern=SHA256_PATTERN)
    execution_mode: ExecutionMode
    twin_snapshot_id: UUID
    producer_operation_key: str | None = None


class ParsedArtifactDiff(RepairModel):
    path: str
    column_reference_replacements: tuple[tuple[str, str], ...]
    join_changed: bool
    filter_changed: bool
    grouping_changed: bool
    grain_changed: bool
    materialization_changed: bool
    macro_changed: bool
    yaml_changed: bool
    test_weakened: bool
    other_sql_changed: bool
    files_changed: tuple[str, ...]
    broader_than_allowed: bool


class RepairRuleResult(RepairModel):
    rule_id: str
    passed: bool
    detail: str


class RepairProposal(RepairModel):
    proposal_id: UUID
    failure_class: FailureClass
    asset: AssetRef
    from_column: str
    to_column: str
    artifact_path: str
    preimage_sha256: str = Field(pattern=SHA256_PATTERN)
    patched_sql: str
    patched_sha256: str = Field(pattern=SHA256_PATTERN)
    hypothesis: str
    hypothesis_hash: str = Field(pattern=SHA256_PATTERN)
    twin_snapshot_id: UUID
    estate_context_sha256: str = Field(pattern=SHA256_PATTERN)
    drift_evidence_ref_id: UUID
    target_environment: str = "DEV"


class RepairValidation(RepairModel):
    allowed: bool
    proposal_id: UUID
    parsed_diff: ParsedArtifactDiff
    rules: tuple[RepairRuleResult, ...]
    reason_codes: tuple[str, ...]
    preimage_sha256: str = Field(pattern=SHA256_PATTERN)
    postimage_sha256: str = Field(pattern=SHA256_PATTERN)


class RepairApplication(RepairModel):
    application_id: UUID
    proposal_id: UUID
    applied: bool
    artifact_path: str
    preimage_sha256: str = Field(pattern=SHA256_PATTERN)
    postimage_sha256: str = Field(pattern=SHA256_PATTERN)
    written_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    gateway_intent_id: UUID | None = None
    project_state_id: UUID | None = None
    applied_at: datetime | None = None


class RepairResult(RepairModel):
    workflow_id: UUID
    failure_class: FailureClass | None
    blocked: bool
    block_reason: str | None = None
    proposal: RepairProposal | None = None
    validation: RepairValidation | None = None
    application: RepairApplication | None = None
    proposal_count: int = Field(ge=0)
    applied_count: int = Field(ge=0)
    post_repair_revalidation_count: int = Field(ge=0)
    recursive_requested: bool = False


class RepairBudgetSnapshot(RepairModel):
    proposal_count: int = Field(ge=0)
    applied_count: int = Field(ge=0)
    applied_count_for_task: int = Field(default=0, ge=0)
    post_repair_revalidation_count: int = Field(ge=0)
    recursive_requested: bool = False
    permission_changed: bool = False
    target_changed: bool = False
    source_data_mutated: bool = False


class ProposeRepairInput(RepairModel):
    failure_class: FailureClass
    asset: AssetRef
    from_column: str
    to_column: str
    old_data_type: str
    new_data_type: str
    added: tuple[DriftColumn, ...]
    removed: tuple[DriftColumn, ...]
    current_columns: tuple[DriftColumn, ...]
    baseline_columns: tuple[DriftColumn, ...]
    artifact_path: str
    artifact_sql: str
    preimage_sha256: str = Field(pattern=SHA256_PATTERN)
    twin_snapshot_id: UUID
    estate_context_sha256: str = Field(pattern=SHA256_PATTERN)
    drift_evidence_ref_id: UUID
    source_authority: SourceAuthorityRef
    target_environment: str = "DEV"


class ValidateRepairInput(RepairModel):
    proposal: RepairProposal
    original_sql: str
    original_files: tuple[tuple[str, str, str], ...]
    drift: DriftEvidence
    budget: RepairBudgetSnapshot
    now: datetime
    static_sql_ok: bool = True


class RepairEventKind(str, Enum):
    PROPOSAL = "PROPOSAL"
    VALIDATION = "VALIDATION"
    APPLICATION = "APPLICATION"
    REVALIDATION = "REVALIDATION"
    BLOCK = "BLOCK"
    VERDICT = "VERDICT"


__all__ = [
    "ACCEPTED_ARTIFACT_PATH",
    "ACCEPTED_ASSET_ADDRESS",
    "ACCEPTED_AUTHORITY_ID",
    "ACCEPTED_FAILURE_CLASS",
    "ACCEPTED_FROM_COLUMN",
    "ACCEPTED_TO_COLUMN",
    "DriftColumn",
    "DriftEvidence",
    "MAX_APPLIED_REPAIRS_PER_TASK",
    "MAX_APPLIED_REPAIRS_PER_WORKFLOW",
    "MAX_CONNECTOR_ATTEMPTS",
    "MAX_POST_REPAIR_REVALIDATIONS",
    "MAX_RECURSIVE_REPAIRS",
    "MAX_REPAIR_PROPOSALS",
    "ParsedArtifactDiff",
    "ProposeRepairInput",
    "RepairApplication",
    "RepairBlockReason",
    "RepairBudgetSnapshot",
    "RepairEventKind",
    "RepairProposal",
    "RepairResult",
    "RepairRuleResult",
    "RepairValidation",
    "ValidateRepairInput",
]
