"""REAL and MOCK mixing must fail where prohibited."""

from __future__ import annotations

from tests.unit.verification.test_verifier import _pack

from aide.domain.artifacts import ExecutionMode
from aide.domain.verification import VerifierVerdict
from aide.verification.evaluate import evaluate_verifier


def test_e_pr_mix_fails() -> None:
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


def test_e_pr_real_rejects_mock() -> None:
    result = evaluate_verifier(_pack(require_real_chain=True))
    assert result.verdict is VerifierVerdict.FAIL
    assert "PROVENANCE_MIX" in result.reason_codes


def test_e_pr_mock_rejects_real() -> None:
    pack = _pack()
    flipped = tuple(
        item.model_copy(update={"execution_mode": ExecutionMode.REAL}) for item in pack.evidence
    )
    result = evaluate_verifier(pack.model_copy(update={"evidence": flipped}))
    assert result.verdict is VerifierVerdict.FAIL
    assert "PROVENANCE_MIX" in result.reason_codes


def test_e_pr_mock_chain_passes() -> None:
    result = evaluate_verifier(_pack(require_real_chain=False))
    assert result.verdict is VerifierVerdict.PASS
