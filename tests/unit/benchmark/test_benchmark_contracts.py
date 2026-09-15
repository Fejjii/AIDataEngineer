from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aide.app.benchmarking.demo import render_demo_report
from aide.app.benchmarking.evidence import completeness_from_bundle
from aide.app.benchmarking.normalize import normalize_text, normalized_digest
from aide.app.benchmarking.runner import compare_fingerprints
from aide.app.supervisor import InterviewResult
from aide.domain.benchmark import MeasurementClass, StableFingerprint
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.roadmap import (
    ACTIVE_DEPENDENCY_EDGES,
    ACTIVE_INTERVIEW_TASKS,
    DEFERRED_AFTER_MVP004,
    dependencies_are_sequential,
    dependency_graph_is_acyclic,
)
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS


def _fingerprint(**overrides: object) -> StableFingerprint:
    digest = "a" * 64
    payload = {
        "phase_sequence": ("RECEIVED", "PLANNING"),
        "asset_selection": (("VANTARA_RAW", "BILLING", "INVOICES"),),
        "normalized_estate_context_digest": digest,
        "model_names": ("stg_billing__invoices", "mart_customer_revenue_daily"),
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
        "capability_sequence": ("discover_assets", "execute_transformation"),
        "workflow_outcome": "VERIFIED",
    }
    payload.update(overrides)
    return StableFingerprint.model_validate(payload)


def test_normalize_replaces_uuids_and_timestamps_not_sql_hashes() -> None:
    uid = str(uuid4())
    text = f"workflow {uid} at 2026-09-15T10:31:00Z"
    assert "<uuid>" in normalize_text(text)
    assert "<timestamp>" in normalize_text(text)
    assert uid not in normalize_text(text)


def test_normalized_digest_is_stable_under_identifier_substitution() -> None:
    left = {"workflow_id": str(uuid4()), "model": "stg_billing__invoices"}
    right = {"workflow_id": str(uuid4()), "model": "stg_billing__invoices"}
    assert normalized_digest(left) == normalized_digest(right)


def test_determinism_fails_when_stable_model_names_differ() -> None:
    left = _fingerprint()
    right = _fingerprint(model_names=("dim_customer",))
    report = compare_fingerprints(left, right)
    assert report.equivalent is False
    assert any(item.field == "model_names" for item in report.mismatches)
    assert "workflow_id" in report.variable_fields
    assert report.normalization_rules


def test_determinism_passes_for_identical_stable_fingerprints() -> None:
    left = _fingerprint()
    right = _fingerprint()
    assert compare_fingerprints(left, right).equivalent is True


def test_measurement_class_has_three_explicit_states() -> None:
    assert {item.value for item in MeasurementClass} == {
        "MEASURED",
        "ESTIMATED",
        "UNAVAILABLE",
    }


def test_active_roadmap_is_sequential_and_acyclic() -> None:
    assert ACTIVE_INTERVIEW_TASKS == ("MVP001", "MVP002", "MVP003", "MVP004")
    assert dependency_graph_is_acyclic(ACTIVE_DEPENDENCY_EDGES)
    assert dependencies_are_sequential(ACTIVE_INTERVIEW_TASKS, ACTIVE_DEPENDENCY_EDGES)
    assert "DE015" in DEFERRED_AFTER_MVP004
    assert "MVP005" not in ACTIVE_INTERVIEW_TASKS


def test_completeness_fails_when_bundle_is_missing() -> None:
    report = completeness_from_bundle(None)
    assert report.complete is False
    assert report.completeness_pct == 0
    assert report.missing_sections == REQUIRED_EVIDENCE_SECTIONS


def test_demo_report_contains_interview_story() -> None:
    principal = PrincipalRef(
        principal_id=uuid4(),
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=uuid4(),
    )
    result = InterviewResult(
        workflow_id=uuid4(),
        principal=principal,
        grants=GrantAuthorization(
            principal=principal,
            requested=frozenset({PermissionLevel.READ}),
            effective=frozenset({PermissionLevel.READ}),
            environment_policy_version="test",
            decided_at=datetime.now(UTC).replace(tzinfo=None),
        ),
        parse_ok=True,
        compile_ok=True,
        execute_ok=True,
        tests_ok=True,
    )
    text = render_demo_report(result)
    assert "Business request:" in text
    assert "Independent Verifier:" in text
    assert "Evidence bundle digest:" in text
    assert "Final:" in text
