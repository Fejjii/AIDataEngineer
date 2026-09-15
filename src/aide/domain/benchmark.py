"""Typed Interview MVP benchmark contracts. Domain-only: no connectors or gateway."""

from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.twin import SHA256_PATTERN
from aide.domain.verification import VerifierVerdict

INTERVIEW_SCENARIO_ID = "interview_mvp_customer_revenue_schema_drift"
INTERVIEW_REQUEST = (
    "Build a customer revenue analytical data product from CRM and billing data."
)

# Labelled baseline minutes from docs/EVALUATION_STRATEGY.md §4 for steps this
# closed loop actually performs. Not a financial ROI claim.
AUTOMATED_ENGINEERING_STEPS: tuple[tuple[str, int], ...] = (
    ("find_relevant_sources", 60),
    ("profile_sources", 90),
    ("decide_model_design", 60),
    ("write_staging_models", 120),
    ("write_intermediate_models", 60),
    ("write_dims_facts_marts", 180),
    ("write_tests_and_yaml", 60),
    ("debug_renamed_column", 30),
    ("reconcile_totals", 30),
)
DEFERRED_MANUAL_STEPS: tuple[tuple[str, int], ...] = (
    ("debug_duplicate_payments", 45),
    ("write_docs_and_lineage", 60),
    ("branch_commit_pr", 20),
)


class BenchmarkModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MeasurementClass(str, Enum):
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"
    UNAVAILABLE = "UNAVAILABLE"


class BenchmarkVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class LiveSmokeStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    CREDENTIAL_GATED = "CREDENTIAL_GATED"
    NOT_RUN = "NOT_RUN"


class ClassifiedMeasurement(BenchmarkModel):
    name: str = Field(min_length=1)
    classification: MeasurementClass
    value: str | None = None
    unit: str | None = None
    notes: str = ""


class NormalizationRule(BenchmarkModel):
    field: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class DeterminismMismatch(BenchmarkModel):
    field: str
    left: str
    right: str


class ScorecardRow(BenchmarkModel):
    name: str
    verdict: BenchmarkVerdict
    measurement: MeasurementClass
    detail: str = ""


class ValueMetrics(BenchmarkModel):
    relevant_assets_analyzed: int = Field(ge=0)
    models_generated: int = Field(ge=0)
    governed_tool_operations: int = Field(ge=0)
    policy_evaluations: int = Field(ge=0)
    detected_incidents: int = Field(ge=0)
    automatic_repairs: int = Field(ge=0)
    human_interventions: int = Field(ge=0)
    tests_executed: int = Field(ge=0)
    quality_checks_executed: int = Field(ge=0)
    evidence_completeness_pct: int = Field(ge=0, le=100)
    total_workflow_duration_ms: int = Field(ge=0)
    repair_duration_ms: int = Field(ge=0)
    estimated_engineering_steps_automated: int = Field(ge=0)
    estimated_engineering_minutes_automated: int = Field(ge=0)


class EvidenceCompleteness(BenchmarkModel):
    required_sections: tuple[str, ...]
    present_sections: tuple[str, ...]
    missing_sections: tuple[str, ...]
    digest_mismatches: tuple[str, ...]
    completeness_pct: int = Field(ge=0, le=100)
    complete: bool


class StableFingerprint(BenchmarkModel):
    """Deterministic fields after explicit normalization of variable identifiers."""

    phase_sequence: tuple[str, ...]
    asset_selection: tuple[tuple[str, ...], ...]
    normalized_estate_context_digest: str = Field(pattern=SHA256_PATTERN)
    model_names: tuple[str, ...]
    generated_content_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    plan_digest: str = Field(pattern=SHA256_PATTERN)
    repair_class: str | None = None
    repair_count: int = Field(ge=0)
    test_outcome: bool
    quality_outcome: bool
    reconciliation_outcome: bool
    parse_ok: bool
    compile_ok: bool
    execute_ok: bool
    verifier_verdict: str | None = None
    verifier_check_vector: tuple[tuple[str, bool, str], ...]
    before_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    after_artifact_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    normalized_evidence_digest: str = Field(pattern=SHA256_PATTERN)
    fixture_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    capability_sequence: tuple[str, ...]
    workflow_outcome: str


class BenchmarkRunRecord(BenchmarkModel):
    workflow_id: UUID
    workflow_outcome: str
    verifier_verdict: VerifierVerdict | None
    phase_sequence: tuple[str, ...]
    asset_selection: tuple[tuple[str, ...], ...]
    estate_context_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    model_names: tuple[str, ...]
    repair_class: str | None = None
    repair_count: int = Field(ge=0)
    test_outcome: bool
    quality_outcome: bool
    reconciliation_outcome: bool
    evidence_completeness: EvidenceCompleteness
    retry_count: int = Field(ge=0)
    human_intervention_count: int = Field(ge=0)
    tests_executed: int = Field(default=0, ge=0)
    quality_checks_executed: int = Field(default=0, ge=0)
    governed_tool_operations: int = Field(default=0, ge=0)
    policy_evaluations: int = Field(default=0, ge=0)
    wall_clock_duration_ms: int = Field(ge=0)
    step_durations_ms: tuple[tuple[str, int], ...] = ()
    repair_duration_ms: int = Field(default=0, ge=0)
    measurements: tuple[ClassifiedMeasurement, ...] = ()
    fingerprint: StableFingerprint
    evidence_bundle_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    fail_reason: str | None = None
    block_reason: str | None = None


class DeterminismReport(BenchmarkModel):
    equivalent: bool
    compared_fields: tuple[str, ...]
    mismatches: tuple[DeterminismMismatch, ...]
    variable_fields: tuple[str, ...]
    normalization_rules: tuple[NormalizationRule, ...]


class BenchmarkResult(BenchmarkModel):
    scenario_id: str
    workflow_outcome: str
    verifier_verdict: VerifierVerdict | None
    verdict: BenchmarkVerdict
    runs: tuple[BenchmarkRunRecord, BenchmarkRunRecord]
    determinism: DeterminismReport
    scorecard: tuple[ScorecardRow, ...]
    value_metrics: ValueMetrics
    evidence_completeness: EvidenceCompleteness
    live_smoke: LiveSmokeStatus = LiveSmokeStatus.NOT_RUN
    live_smoke_detail: str = ""


NORMALIZATION_RULES: tuple[NormalizationRule, ...] = (
    NormalizationRule(
        field="workflow_id",
        rule="replace UUID with <uuid>",
        reason="new workflow identity is allocated per run",
    ),
    NormalizationRule(
        field="twin_snapshot_id",
        rule="replace UUID with <uuid>",
        reason="snapshot identity is allocated at pin time",
    ),
    NormalizationRule(
        field="asset_id",
        rule="replace UUID with <uuid>",
        reason="twin asset identity is allocated at capture",
    ),
    NormalizationRule(
        field="evidence_ref_id",
        rule="replace UUID with <uuid>",
        reason="evidence references are unique per persistence",
    ),
    NormalizationRule(
        field="intent_id",
        rule="replace UUID with <uuid>",
        reason="gateway intent identity is allocated per dispatch",
    ),
    NormalizationRule(
        field="timestamps",
        rule="replace ISO-8601 datetimes with <timestamp>",
        reason="observed_at, created_at, and capture times differ per run",
    ),
    NormalizationRule(
        field="wall_time_ms",
        rule="exclude from stable fingerprint; keep as MEASURED timing",
        reason="wall clock is intentionally variable",
    ),
    NormalizationRule(
        field="step_durations_ms",
        rule="exclude duration values from stable fingerprint; keep step names",
        reason="step durations vary with host load",
    ),
    NormalizationRule(
        field="estate_context_sha256",
        rule="hash canonical context after UUID and timestamp substitution",
        reason="raw digest includes snapshot and observation identifiers",
    ),
    NormalizationRule(
        field="evidence_bundle_sha256",
        rule="hash required section names plus content hashes after UUID substitution",
        reason="outer bundle digest includes workflow_id and evidence_ref_id",
    ),
)

VARIABLE_FINGERPRINT_FIELDS: tuple[str, ...] = (
    "workflow_id",
    "principal_id",
    "session_id",
    "twin_snapshot_id",
    "asset_id",
    "observation_id",
    "evidence_ref_id",
    "intent_id",
    "attempt_id",
    "phase_run_id",
    "task_id",
    "proposal_id",
    "application_id",
    "captured_at",
    "observed_at",
    "created_at",
    "applied_at",
    "fresh_until",
    "wall_time_ms",
    "step_durations_ms",
    "repair_duration_ms",
    "raw_estate_context_sha256",
    "raw_evidence_bundle_sha256",
)


__all__ = [
    "AUTOMATED_ENGINEERING_STEPS",
    "DEFERRED_MANUAL_STEPS",
    "INTERVIEW_REQUEST",
    "INTERVIEW_SCENARIO_ID",
    "NORMALIZATION_RULES",
    "VARIABLE_FINGERPRINT_FIELDS",
    "BenchmarkResult",
    "BenchmarkRunRecord",
    "BenchmarkVerdict",
    "ClassifiedMeasurement",
    "DeterminismMismatch",
    "DeterminismReport",
    "EvidenceCompleteness",
    "LiveSmokeStatus",
    "MeasurementClass",
    "NormalizationRule",
    "ScorecardRow",
    "StableFingerprint",
    "ValueMetrics",
]
