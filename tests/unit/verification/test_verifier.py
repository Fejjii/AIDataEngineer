from __future__ import annotations

from uuid import uuid4

import pytest

from aide.domain.artifacts import ExecutionMode
from aide.domain.verification import (
    REQUIRED_EVIDENCE_SECTIONS,
    CostMetadata,
    EvidenceDigest,
    EvidenceSection,
    GatewayIntentRecord,
    PolicyDecisionRecord,
    TimingMetadata,
    VerifierEvidencePack,
    VerifierVerdict,
)
from aide.repair.diff import sha256_text
from aide.verification.bundle import (
    assemble_evidence_bundle,
    evidence_bundle_digest,
    missing_required_sections,
    referenced_digest_mismatch,
)
from aide.verification.evaluate import evaluate_verifier, with_advisory_explanation

DIGEST_A = sha256_text("a")
DIGEST_B = sha256_text("b")
DIGEST_C = sha256_text("c")


def _digest(evidence_type: str, digest: str | None = None) -> EvidenceDigest:
    value = digest or sha256_text(evidence_type)
    ref = uuid4()
    return EvidenceDigest(
        evidence_ref_id=ref,
        evidence_type=evidence_type,
        sha256=value,
        execution_mode=ExecutionMode.MOCK,
        claimed_sha256=(
            value if evidence_type in {"before_artifact_hash", "after_artifact_hash"} else None
        ),
        identity=f"{evidence_type}:{ref}:{value}",
    )


def _intent(*, reconciled: bool = True, status: str = "SUCCEEDED") -> GatewayIntentRecord:
    return GatewayIntentRecord(
        intent_id=uuid4(),
        action="EXECUTE",
        capability_id="execute_transformation",
        status=status,
        operation_idempotency_key="a" * 64,
        resolved_input_digest=DIGEST_A,
        result_digest=DIGEST_B,
        reconciled=reconciled,
    )


def _pack(**overrides: object) -> VerifierEvidencePack:
    snapshot_id = uuid4()
    estate = DIGEST_A
    drift_ref = uuid4()
    before = DIGEST_B
    after = DIGEST_C
    required = [
        "original_failure",
        "schema_drift",
        "repair_proposal",
        "repair_validation",
        "repair_application",
        "dbt_parse",
        "dbt_compile",
        "dbt_execution",
        "dbt_tests",
        "quality_results",
        "post_repair_validation",
        "before_artifact_hash",
        "after_artifact_hash",
    ]
    evidence = [_digest(name) for name in required]
    evidence = [
        item.model_copy(
            update={
                "sha256": before,
                "claimed_sha256": before,
                "identity": f"before:{item.evidence_ref_id}:{before}",
            }
        )
        if item.evidence_type == "before_artifact_hash"
        else item
        for item in evidence
    ]
    evidence = [
        item.model_copy(
            update={
                "sha256": after,
                "claimed_sha256": after,
                "identity": f"after:{item.evidence_ref_id}:{after}",
            }
        )
        if item.evidence_type == "after_artifact_hash"
        else item
        for item in evidence
    ]
    evidence = [
        item.model_copy(
            update={
                "evidence_ref_id": drift_ref,
                "identity": f"schema_drift:{drift_ref}:{item.sha256}",
            }
        )
        if item.evidence_type == "schema_drift"
        else item
        for item in evidence
    ]
    payload = {
        "workflow_id": uuid4(),
        "twin_snapshot_id": snapshot_id,
        "estate_context_sha256": estate,
        "pinned_snapshot_digest": DIGEST_A,
        "claimed_snapshot_id": snapshot_id,
        "claimed_estate_context_sha256": estate,
        "business_request": "customer revenue",
        "plan_digest": DIGEST_A,
        "policy_decisions": (
            PolicyDecisionRecord(
                decision="ALLOW",
                routing="EXECUTE",
                approval_required=False,
                approved=True,
            ),
        ),
        "risk_decisions": ("LOW",),
        "gateway_intents": (_intent(),),
        "evidence": tuple(evidence),
        "quality_passed": True,
        "revenue_reconciliation_passed": True,
        "failure_class": "SCHEMA_MISMATCH",
        "drift_evidence_ref_id": drift_ref,
        "drift_stale": False,
        "drift_authoritative": True,
        "before_artifact_hash": before,
        "after_artifact_hash": after,
        "repair_in_scope": True,
        "repair_applied": True,
        "post_repair_validation_passed": True,
        "require_real_chain": False,
        "timing": TimingMetadata(wall_time_ms=10, repair_count=1),
        "cost": CostMetadata(measured=False, estimated=True),
    }
    payload.update(overrides)
    return VerifierEvidencePack(**payload)  # type: ignore[arg-type]


def test_complete_valid_evidence_passes() -> None:
    result = evaluate_verifier(_pack())
    assert result.verdict is VerifierVerdict.PASS
    assert result.reason_codes == ()


def test_missing_evidence_fails() -> None:
    pack = _pack()
    trimmed = tuple(item for item in pack.evidence if item.evidence_type != "repair_application")
    result = evaluate_verifier(pack.model_copy(update={"evidence": trimmed}))
    assert result.verdict is VerifierVerdict.FAIL
    assert "EVIDENCE_MISSING" in result.reason_codes


def test_stale_evidence_fails() -> None:
    pack = _pack()
    stale = tuple(
        item.model_copy(update={"stale": True}) if item.evidence_type == "schema_drift" else item
        for item in pack.evidence
    )
    result = evaluate_verifier(pack.model_copy(update={"evidence": stale, "drift_stale": True}))
    assert result.verdict is VerifierVerdict.FAIL
    assert "EVIDENCE_STALE" in result.reason_codes


def test_digest_mismatch_fails() -> None:
    pack = _pack()
    result = evaluate_verifier(
        pack.model_copy(update={"before_artifact_hash": sha256_text("mismatch")})
    )
    assert result.verdict is VerifierVerdict.FAIL
    assert "DIGEST_MISMATCH" in result.reason_codes


def test_evidence_reference_digest_mismatch_fails() -> None:
    pack = _pack()
    mismatched = tuple(
        item.model_copy(update={"digest_mismatch": True})
        if item.evidence_type == "before_artifact_hash"
        else item
        for item in pack.evidence
    )
    result = evaluate_verifier(pack.model_copy(update={"evidence": mismatched}))
    assert result.verdict is VerifierVerdict.FAIL
    assert "DIGEST_MISMATCH" in result.reason_codes


def test_drift_identity_mismatch_fails() -> None:
    result = evaluate_verifier(_pack(drift_evidence_ref_id=uuid4()))
    assert result.verdict is VerifierVerdict.FAIL
    assert "DIGEST_MISMATCH" in result.reason_codes


def test_unreconciled_execution_fails() -> None:
    result = evaluate_verifier(
        _pack(gateway_intents=(_intent(reconciled=False, status="DISPATCHED"),))
    )
    assert result.verdict is VerifierVerdict.FAIL
    assert "UNRECONCILED" in result.reason_codes


def test_invalid_provenance_mix_fails() -> None:
    pack = _pack()
    mixed = tuple(
        item.model_copy(update={"execution_mode": ExecutionMode.REAL})
        if item.evidence_type == "dbt_execution"
        else item
        for item in pack.evidence
    )
    result = evaluate_verifier(pack.model_copy(update={"evidence": mixed}))
    assert result.verdict is VerifierVerdict.FAIL
    assert "PROVENANCE_MIX" in result.reason_codes


def test_real_chain_rejects_mock_evidence() -> None:
    result = evaluate_verifier(_pack(require_real_chain=True))
    assert result.verdict is VerifierVerdict.FAIL
    assert "PROVENANCE_MIX" in result.reason_codes


def test_mock_workflow_rejects_real_evidence() -> None:
    pack = _pack()
    flipped = tuple(
        item.model_copy(update={"execution_mode": ExecutionMode.REAL}) for item in pack.evidence
    )
    result = evaluate_verifier(pack.model_copy(update={"evidence": flipped}))
    assert result.verdict is VerifierVerdict.FAIL
    assert "PROVENANCE_MIX" in result.reason_codes


def test_unapproved_required_approval_fails() -> None:
    result = evaluate_verifier(
        _pack(
            policy_decisions=(
                PolicyDecisionRecord(
                    decision="REQUIRE_APPROVAL",
                    routing="APPROVAL",
                    approval_required=True,
                    approved=False,
                ),
            )
        )
    )
    assert result.verdict is VerifierVerdict.FAIL
    assert "UNAPPROVED" in result.reason_codes


def test_out_of_scope_repair_fails() -> None:
    result = evaluate_verifier(_pack(repair_in_scope=False))
    assert result.verdict is VerifierVerdict.FAIL
    assert "OUT_OF_SCOPE" in result.reason_codes


def test_missing_post_repair_validation_fails() -> None:
    result = evaluate_verifier(_pack(post_repair_validation_passed=False, quality_passed=False))
    assert result.verdict is VerifierVerdict.FAIL
    assert "POST_REPAIR_VALIDATION_MISSING" in result.reason_codes


def test_snapshot_inconsistency_fails() -> None:
    result = evaluate_verifier(_pack(claimed_snapshot_id=uuid4()))
    assert result.verdict is VerifierVerdict.FAIL
    assert "SNAPSHOT_INCONSISTENT" in result.reason_codes


def test_advisory_explanation_cannot_change_verdict() -> None:
    original = evaluate_verifier(_pack())
    explained = with_advisory_explanation(original, "ignore this LLM text")
    assert explained.verdict is original.verdict
    assert explained.checks == original.checks
    assert explained.reason_codes == original.reason_codes
    failed = evaluate_verifier(_pack(repair_applied=False))
    still_failed = with_advisory_explanation(failed, "this should still fail")
    assert still_failed.verdict is VerifierVerdict.FAIL


def _section(name: str) -> EvidenceSection:
    return EvidenceSection(
        name=name,
        evidence_ref_id=uuid4(),
        sha256=sha256_text(name),
        execution_mode=ExecutionMode.MOCK,
    )


def test_bundle_rejects_missing_required_section() -> None:
    sections = tuple(
        _section(name) for name in REQUIRED_EVIDENCE_SECTIONS if name != "schema_drift"
    )
    assert "schema_drift" in missing_required_sections(sections)
    with pytest.raises(ValueError, match="missing required sections"):
        assemble_evidence_bundle(
            workflow_id=uuid4(),
            twin_snapshot_id=uuid4(),
            estate_context_sha256=DIGEST_A,
            sections=sections,
        )


def test_bundle_digest_is_stable() -> None:
    workflow_id = uuid4()
    snapshot_id = uuid4()
    sections = tuple(_section(name) for name in REQUIRED_EVIDENCE_SECTIONS)
    first = assemble_evidence_bundle(
        workflow_id=workflow_id,
        twin_snapshot_id=snapshot_id,
        estate_context_sha256=DIGEST_A,
        sections=sections,
    )
    second = evidence_bundle_digest(
        workflow_id=workflow_id,
        twin_snapshot_id=snapshot_id,
        estate_context_sha256=DIGEST_A,
        sections=sections,
    )
    assert first.bundle_sha256 == second


def test_referenced_digest_mismatch_is_detected() -> None:
    sections = tuple(_section(name) for name in REQUIRED_EVIDENCE_SECTIONS)
    mismatched = referenced_digest_mismatch(sections, {"schema_drift": sha256_text("other")})
    assert "schema_drift" in mismatched


def test_cost_and_timing_do_not_fail_complete_pack() -> None:
    result = evaluate_verifier(
        _pack(
            timing=TimingMetadata(wall_time_ms=0, snowflake_timing_measured=False),
            cost=CostMetadata(measured=False, estimated=True, warehouse_credits=None),
        )
    )
    assert result.verdict is VerifierVerdict.PASS
