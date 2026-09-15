from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aide.app.benchmarking.summary import summarize_interview_demo
from aide.app.supervisor import InterviewResult
from aide.domain.benchmark import (
    INTERVIEW_SCENARIO_ID,
    BenchmarkResult,
    BenchmarkRunRecord,
    BenchmarkVerdict,
    DeterminismReport,
    EvidenceCompleteness,
    LiveSmokeStatus,
    MeasurementClass,
    ScorecardRow,
    StableFingerprint,
    ValueMetrics,
)
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.repair import ACCEPTED_ARTIFACT_PATH, ACCEPTED_FROM_COLUMN, ACCEPTED_TO_COLUMN
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, VerifierVerdict


def _fingerprint() -> StableFingerprint:
    digest = "a" * 64
    return StableFingerprint.model_validate(
        {
            "phase_sequence": ("RECEIVED", "PLANNING"),
            "asset_selection": (("VANTARA_RAW", "BILLING", "INVOICES"),),
            "normalized_estate_context_digest": digest,
            "model_names": ("stg_billing__invoices",),
            "generated_content_sha256": digest,
            "plan_digest": digest,
            "repair_class": "SCHEMA_MISMATCH",
            "repair_count": 1,
            "test_outcome": True,
            "quality_outcome": True,
            "reconciliation_outcome": True,
            "parse_ok": True,
            "compile_ok": True,
            "execute_ok": True,
            "verifier_verdict": "PASS",
            "verifier_check_vector": (("snapshot_identity", True, "SNAPSHOT_INCONSISTENT"),),
            "before_artifact_hash": "b" * 64,
            "after_artifact_hash": "c" * 64,
            "normalized_evidence_digest": digest,
            "fixture_digest": digest,
            "capability_sequence": ("discover_assets",),
            "workflow_outcome": "VERIFIED",
        }
    )


def _completeness() -> EvidenceCompleteness:
    return EvidenceCompleteness(
        required_sections=REQUIRED_EVIDENCE_SECTIONS,
        present_sections=REQUIRED_EVIDENCE_SECTIONS,
        missing_sections=(),
        digest_mismatches=(),
        completeness_pct=100,
        complete=True,
    )


def _run() -> BenchmarkRunRecord:
    return BenchmarkRunRecord(
        workflow_id=uuid4(),
        workflow_outcome="VERIFIED",
        verifier_verdict=VerifierVerdict.PASS,
        phase_sequence=("RECEIVED", "PLANNING"),
        asset_selection=(("VANTARA_RAW", "BILLING", "INVOICES"),),
        estate_context_sha256="d" * 64,
        model_names=("stg_billing__invoices",),
        repair_class="SCHEMA_MISMATCH",
        repair_count=1,
        test_outcome=True,
        quality_outcome=True,
        reconciliation_outcome=True,
        evidence_completeness=_completeness(),
        retry_count=0,
        human_intervention_count=0,
        tests_executed=23,
        quality_checks_executed=25,
        governed_tool_operations=36,
        policy_evaluations=36,
        wall_clock_duration_ms=10,
        fingerprint=_fingerprint(),
        evidence_bundle_sha256="e" * 64,
    )


def _result() -> InterviewResult:
    principal = PrincipalRef(
        principal_id=uuid4(),
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=uuid4(),
    )
    return InterviewResult(
        workflow_id=uuid4(),
        principal=principal,
        grants=GrantAuthorization(
            principal=principal,
            requested=frozenset({PermissionLevel.READ}),
            effective=frozenset({PermissionLevel.READ}),
            environment_policy_version="test",
            decided_at=datetime.now(UTC).replace(tzinfo=None),
        ),
        estate_context_sha256="d" * 64,
    )


def test_summary_is_bounded_and_has_expected_repair_contract() -> None:
    first_run = _run()
    second_run = _run()
    report = BenchmarkResult(
        scenario_id=INTERVIEW_SCENARIO_ID,
        workflow_outcome="VERIFIED",
        verifier_verdict=VerifierVerdict.PASS,
        verdict=BenchmarkVerdict.PASS,
        runs=(first_run, second_run),
        determinism=DeterminismReport(
            equivalent=True,
            compared_fields=("model_names",),
            mismatches=(),
            variable_fields=("workflow_id",),
            normalization_rules=(),
        ),
        scorecard=(
            ScorecardRow(
                name="repair_correctness",
                verdict=BenchmarkVerdict.PASS,
                measurement=MeasurementClass.MEASURED,
            ),
        ),
        value_metrics=ValueMetrics(
            relevant_assets_analyzed=10,
            models_generated=21,
            governed_tool_operations=36,
            policy_evaluations=36,
            detected_incidents=1,
            automatic_repairs=1,
            human_interventions=0,
            tests_executed=23,
            quality_checks_executed=25,
            evidence_completeness_pct=100,
            total_workflow_duration_ms=10,
            repair_duration_ms=1,
            estimated_engineering_steps_automated=9,
            estimated_engineering_minutes_automated=690,
        ),
        evidence_completeness=_completeness(),
        live_smoke=LiveSmokeStatus.NOT_RUN,
    )
    summary = summarize_interview_demo(report, _result())
    payload = summary.model_dump(mode="json")
    assert summary.schema_drift.detected is True
    assert summary.schema_drift.mapping == f"{ACCEPTED_FROM_COLUMN} → {ACCEPTED_TO_COLUMN}"
    assert summary.repair.apply_count == 1
    assert summary.repair.artifact_path == ACCEPTED_ARTIFACT_PATH
    assert summary.verifier_verdict == "PASS"
    assert summary.evidence_completeness_pct == 100
    assert summary.determinism is True
    assert summary.benchmark_metrics.human_interventions == 0
    assert "AIDE_DATABASE_URL" not in payload
    assert "SNOWFLAKE_ACCOUNT" not in str(payload)
    assert "AIDE_CSRF_SECRET" not in str(payload)
    assert "POSTGRES_PASSWORD" not in str(payload)
