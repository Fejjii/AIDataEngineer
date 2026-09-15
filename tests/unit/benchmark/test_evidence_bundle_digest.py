from __future__ import annotations

from uuid import uuid4

from aide.domain.artifacts import ExecutionMode
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, EvidenceSection
from aide.repair.diff import sha256_text
from aide.verification.bundle import assemble_evidence_bundle, evidence_bundle_digest


def _sections() -> tuple[EvidenceSection, ...]:
    return tuple(
        EvidenceSection(
            name=name,
            evidence_ref_id=uuid4(),
            sha256=sha256_text(name),
            execution_mode=ExecutionMode.MOCK,
        )
        for name in REQUIRED_EVIDENCE_SECTIONS
    )


def test_tampered_bundle_sha256_does_not_match_recomputed_digest() -> None:
    workflow_id = uuid4()
    snapshot_id = uuid4()
    estate = sha256_text("estate")
    sections = _sections()
    bundle = assemble_evidence_bundle(
        workflow_id=workflow_id,
        twin_snapshot_id=snapshot_id,
        estate_context_sha256=estate,
        sections=sections,
    )
    tampered = bundle.model_copy(update={"bundle_sha256": "0" * 64})
    recomputed = evidence_bundle_digest(
        workflow_id=tampered.workflow_id,
        twin_snapshot_id=tampered.twin_snapshot_id,
        estate_context_sha256=tampered.estate_context_sha256,
        sections=tampered.sections,
    )
    assert recomputed == bundle.bundle_sha256
    assert recomputed != tampered.bundle_sha256


def test_wrong_workflow_or_snapshot_changes_recomputed_manifest_identity() -> None:
    workflow_id = uuid4()
    snapshot_id = uuid4()
    estate = sha256_text("estate")
    sections = _sections()
    original = evidence_bundle_digest(
        workflow_id=workflow_id,
        twin_snapshot_id=snapshot_id,
        estate_context_sha256=estate,
        sections=sections,
    )
    other_workflow = evidence_bundle_digest(
        workflow_id=uuid4(),
        twin_snapshot_id=snapshot_id,
        estate_context_sha256=estate,
        sections=sections,
    )
    other_snapshot = evidence_bundle_digest(
        workflow_id=workflow_id,
        twin_snapshot_id=uuid4(),
        estate_context_sha256=estate,
        sections=sections,
    )
    assert original != other_workflow
    assert original != other_snapshot
