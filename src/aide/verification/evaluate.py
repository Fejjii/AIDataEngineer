"""Read-only Independent Verifier. Deterministic PASS/FAIL over immutable evidence."""

from __future__ import annotations

from aide.domain.artifacts import ExecutionMode
from aide.domain.verification import (
    EvidenceDigest,
    VerifierCheck,
    VerifierEvidencePack,
    VerifierReasonCode,
    VerifierResult,
    VerifierVerdict,
)


def evaluate_verifier(pack: VerifierEvidencePack) -> VerifierResult:
    """Derive PASS or FAIL from deterministic checks only. No I/O."""
    checks: list[VerifierCheck] = []

    def add(check_id: str, passed: bool, reason: VerifierReasonCode, detail: str) -> None:
        checks.append(
            VerifierCheck(
                check_id=check_id,
                passed=passed,
                reason_code=reason.value,
                detail=detail,
            )
        )

    add(
        "snapshot_identity",
        pack.twin_snapshot_id == pack.claimed_snapshot_id,
        VerifierReasonCode.SNAPSHOT_INCONSISTENT,
        "pinned TwinSnapshot identity must match every downstream claim",
    )
    add(
        "estate_context_identity",
        pack.estate_context_sha256 == pack.claimed_estate_context_sha256,
        VerifierReasonCode.ESTATE_CONTEXT_INCONSISTENT,
        "pinned EstateContext digest must match every downstream claim",
    )
    required_types = {
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
    }
    present_types = {item.evidence_type for item in pack.evidence}
    missing = sorted(required_types.difference(present_types))
    add(
        "required_evidence_present",
        not missing,
        VerifierReasonCode.EVIDENCE_MISSING,
        "missing:" + ",".join(missing) if missing else "all required evidence types present",
    )
    add(
        "drift_present",
        pack.drift_evidence_ref_id is not None,
        VerifierReasonCode.EVIDENCE_MISSING,
        "schema drift evidence reference",
    )
    add(
        "drift_not_stale",
        not pack.drift_stale,
        VerifierReasonCode.EVIDENCE_STALE,
        "drift evidence freshness",
    )
    add(
        "drift_authoritative",
        pack.drift_authoritative,
        VerifierReasonCode.OUT_OF_SCOPE,
        "Snowflake metadata is the authoritative drift source",
    )
    identities = [item.identity for item in pack.evidence]
    add(
        "evidence_identity",
        len(identities) == len(set(identities)),
        VerifierReasonCode.DIGEST_MISMATCH,
        "evidence identities must be unique",
    )
    digest_ok = all(len(item.sha256) == 64 for item in pack.evidence)
    add(
        "evidence_digest_shape",
        digest_ok,
        VerifierReasonCode.DIGEST_MISMATCH,
        "every evidence reference carries a 64-hex digest",
    )
    add(
        "before_after_hashes",
        pack.before_artifact_hash is not None
        and pack.after_artifact_hash is not None
        and pack.before_artifact_hash != pack.after_artifact_hash,
        VerifierReasonCode.EVIDENCE_MISSING,
        "before and after artifact hashes",
    )
    by_type = {item.evidence_type: item for item in pack.evidence}
    drift_item = by_type.get("schema_drift")
    add(
        "drift_digest_identity",
        pack.drift_evidence_ref_id is None
        or (drift_item is not None and drift_item.evidence_ref_id == pack.drift_evidence_ref_id),
        VerifierReasonCode.DIGEST_MISMATCH,
        "schema drift evidence identity must match the claimed reference",
    )
    add(
        "evidence_reference_digests",
        not any(item.digest_mismatch for item in pack.evidence),
        VerifierReasonCode.DIGEST_MISMATCH,
        "persisted evidence reference digests must match immutable artifact bodies",
    )
    before_item = by_type.get("before_artifact_hash")
    after_item = by_type.get("after_artifact_hash")
    add(
        "artifact_hash_digests",
        _claimed_hash_matches(before_item, pack.before_artifact_hash)
        and _claimed_hash_matches(after_item, pack.after_artifact_hash),
        VerifierReasonCode.DIGEST_MISMATCH,
        "persisted claimed artifact hashes must match repair proposal/application hashes",
    )
    stale_items = [item.identity for item in pack.evidence if item.stale]
    add(
        "no_stale_evidence",
        not stale_items,
        VerifierReasonCode.EVIDENCE_STALE,
        ",".join(stale_items) if stale_items else "no stale evidence",
    )
    modes = {item.execution_mode for item in pack.evidence}
    mixed = ExecutionMode.REAL in modes and ExecutionMode.MOCK in modes
    invalid_mix = mixed or (pack.require_real_chain and ExecutionMode.MOCK in modes)
    add(
        "provenance_consistent",
        not invalid_mix,
        VerifierReasonCode.PROVENANCE_MIX,
        "REAL and MOCK evidence must not mix in a live verdict",
    )
    unapproved = [
        item for item in pack.policy_decisions if item.approval_required and not item.approved
    ]
    add(
        "approvals",
        not unapproved,
        VerifierReasonCode.UNAPPROVED,
        "approval-required decisions must have an effective approval",
    )
    unreconciled = [item.intent_id for item in pack.gateway_intents if not item.reconciled]
    open_intents = [
        item.intent_id
        for item in pack.gateway_intents
        if item.status in {"DISPATCHED", "OUTCOME_AMBIGUOUS"}
    ]
    add(
        "reconciled",
        not unreconciled and not open_intents,
        VerifierReasonCode.UNRECONCILED,
        "every gateway dispatch must be reconciled before a PASS verdict",
    )
    add(
        "repair_in_scope",
        pack.repair_in_scope,
        VerifierReasonCode.OUT_OF_SCOPE,
        "only the allow-listed INVOICE_STATUS→STATUS repair is in scope",
    )
    add(
        "repair_applied",
        pack.repair_applied,
        VerifierReasonCode.REPAIR_NOT_APPLIED,
        "validated repair must be applied once",
    )
    add(
        "post_repair_validation",
        pack.post_repair_validation_passed is True
        and pack.quality_passed
        and pack.revenue_reconciliation_passed,
        VerifierReasonCode.POST_REPAIR_VALIDATION_MISSING,
        "post-repair dbt tests, quality, and reconciliation must pass",
    )
    add(
        "failure_classified",
        pack.failure_class == "SCHEMA_MISMATCH",
        VerifierReasonCode.OUT_OF_SCOPE,
        pack.failure_class or "missing failure class",
    )
    add(
        "timing_present",
        pack.timing.wall_time_ms >= 0,
        VerifierReasonCode.EVIDENCE_MISSING,
        "timing metadata does not affect correctness",
    )
    add(
        "cost_present",
        pack.cost.measured or pack.cost.estimated,
        VerifierReasonCode.EVIDENCE_MISSING,
        "cost metadata is recorded as measured or estimated",
    )
    failed = tuple(item for item in checks if not item.passed)
    verdict = VerifierVerdict.PASS if not failed else VerifierVerdict.FAIL
    reason_codes = tuple(item.reason_code for item in failed)
    return VerifierResult(
        verdict=verdict,
        checks=tuple(checks),
        reason_codes=reason_codes,
        twin_snapshot_id=pack.twin_snapshot_id,
        estate_context_sha256=pack.estate_context_sha256,
        advisory_explanation=None,
    )


def _claimed_hash_matches(item: EvidenceDigest | None, expected: str | None) -> bool:
    if item is None or expected is None:
        return True
    return item.claimed_sha256 is not None and item.claimed_sha256 == expected


def with_advisory_explanation(result: VerifierResult, text: str | None) -> VerifierResult:
    """Store optional LLM text after the verdict. It cannot change checks or verdict."""
    return result.model_copy(update={"advisory_explanation": text})


__all__ = ["evaluate_verifier", "with_advisory_explanation"]
