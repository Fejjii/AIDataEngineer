"""Independent Verifier and evidence-bundle contracts. Domain-only."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aide.domain.artifacts import ExecutionMode
from aide.domain.twin import SHA256_PATTERN

REQUIRED_EVIDENCE_SECTIONS: tuple[str, ...] = (
    "request",
    "twin_snapshot",
    "estate_context",
    "plan",
    "policy_decisions",
    "risk_decisions",
    "gateway_intents",
    "attempts",
    "reconciliation",
    "dbt_artifacts",
    "quality_results",
    "revenue_payment_reconciliation",
    "original_failure",
    "schema_drift",
    "repair_proposal",
    "repair_validation",
    "before_artifact_hash",
    "approved_parsed_diff",
    "repair_application",
    "after_artifact_hash",
    "dbt_parse",
    "dbt_compile",
    "dbt_execution",
    "dbt_tests",
    "post_repair_validation",
    "twin_observations",
    "verifier_verdict",
    "timing_metadata",
    "cost_metadata",
)


class VerificationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class VerifierVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VerifierReasonCode(str, Enum):
    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    PROVENANCE_MIX = "PROVENANCE_MIX"
    UNAPPROVED = "UNAPPROVED"
    UNRECONCILED = "UNRECONCILED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SNAPSHOT_INCONSISTENT = "SNAPSHOT_INCONSISTENT"
    ESTATE_CONTEXT_INCONSISTENT = "ESTATE_CONTEXT_INCONSISTENT"
    REPAIR_NOT_APPLIED = "REPAIR_NOT_APPLIED"
    POST_REPAIR_VALIDATION_MISSING = "POST_REPAIR_VALIDATION_MISSING"


class VerifierCheck(VerificationModel):
    check_id: str = Field(min_length=1)
    passed: bool
    reason_code: str
    detail: str


class TimingMetadata(VerificationModel):
    wall_time_ms: int = Field(ge=0)
    step_durations_ms: tuple[tuple[str, int], ...] = ()
    snowflake_query_ms: int | None = None
    snowflake_timing_measured: bool = False
    dbt_timing_ms: int | None = None
    dbt_timing_measured: bool = False
    retry_count: int = Field(default=0, ge=0)
    repair_count: int = Field(default=0, ge=0)


class CostMetadata(VerificationModel):
    model_tokens: int | None = None
    model_cost_usd: str | None = None
    warehouse_credits: str | None = None
    measured: bool = False
    estimated: bool = True


class EvidenceSection(VerificationModel):
    name: str = Field(min_length=1)
    evidence_ref_id: UUID
    sha256: str = Field(pattern=SHA256_PATTERN)
    execution_mode: ExecutionMode


class EvidenceBundle(VerificationModel):
    """Immutable manifest of evidence references. Not a copy of mutable logs."""

    schema_version: int = Field(default=1, ge=1)
    workflow_id: UUID
    twin_snapshot_id: UUID
    estate_context_sha256: str = Field(pattern=SHA256_PATTERN)
    sections: tuple[EvidenceSection, ...]
    bundle_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def reject_missing_required_sections(self) -> EvidenceBundle:
        present = {item.name for item in self.sections}
        missing = [name for name in REQUIRED_EVIDENCE_SECTIONS if name not in present]
        if missing:
            raise ValueError(f"evidence bundle missing required sections: {missing}")
        names = [item.name for item in self.sections]
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("evidence bundle sections must be unique and sorted by name")
        return self


class VerifierResult(VerificationModel):
    verdict: VerifierVerdict
    checks: tuple[VerifierCheck, ...]
    reason_codes: tuple[str, ...]
    twin_snapshot_id: UUID
    estate_context_sha256: str = Field(pattern=SHA256_PATTERN)
    advisory_explanation: str | None = None


class EvidenceDigest(VerificationModel):
    evidence_ref_id: UUID
    evidence_type: str
    sha256: str = Field(pattern=SHA256_PATTERN)
    execution_mode: ExecutionMode
    stale: bool = False
    identity: str = Field(min_length=1)


class GatewayIntentRecord(VerificationModel):
    intent_id: UUID
    action: str
    capability_id: str
    status: str
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    resolved_input_digest: str = Field(pattern=SHA256_PATTERN)
    result_digest: str | None = None
    evidence_ref_id: UUID | None = None
    approval_id: UUID | None = None
    reconciled: bool = True


class PolicyDecisionRecord(VerificationModel):
    decision: str
    routing: str
    reasons: tuple[str, ...] = ()
    approval_required: bool = False
    approved: bool = False


class VerifierEvidencePack(VerificationModel):
    """Read-only pack assembled by Supervisor. The verifier never loads writers."""

    workflow_id: UUID
    twin_snapshot_id: UUID
    estate_context_sha256: str = Field(pattern=SHA256_PATTERN)
    pinned_snapshot_digest: str = Field(pattern=SHA256_PATTERN)
    claimed_snapshot_id: UUID
    claimed_estate_context_sha256: str = Field(pattern=SHA256_PATTERN)
    business_request: str
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    policy_decisions: tuple[PolicyDecisionRecord, ...]
    risk_decisions: tuple[str, ...]
    approval_records: tuple[tuple[str, str], ...] = ()
    gateway_intents: tuple[GatewayIntentRecord, ...]
    evidence: tuple[EvidenceDigest, ...]
    quality_passed: bool
    revenue_reconciliation_passed: bool
    failure_class: str | None
    drift_evidence_ref_id: UUID | None
    drift_stale: bool = False
    drift_authoritative: bool = False
    before_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    after_artifact_hash: str | None = None
    repair_in_scope: bool = False
    repair_applied: bool = False
    post_repair_validation_passed: bool | None = None
    require_real_chain: bool = False
    timing: TimingMetadata
    cost: CostMetadata


__all__ = [
    "REQUIRED_EVIDENCE_SECTIONS",
    "CostMetadata",
    "EvidenceBundle",
    "EvidenceDigest",
    "EvidenceSection",
    "GatewayIntentRecord",
    "PolicyDecisionRecord",
    "TimingMetadata",
    "VerifierCheck",
    "VerifierEvidencePack",
    "VerifierReasonCode",
    "VerifierResult",
    "VerifierVerdict",
]
