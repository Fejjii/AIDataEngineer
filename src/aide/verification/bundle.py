"""Assemble the immutable evidence-bundle manifest from references."""

from __future__ import annotations

import hashlib
from uuid import UUID

from aide.domain.identity import canonical_json_bytes
from aide.domain.verification import (
    REQUIRED_EVIDENCE_SECTIONS,
    EvidenceBundle,
    EvidenceSection,
)


def evidence_bundle_digest(
    *,
    workflow_id: UUID,
    twin_snapshot_id: UUID,
    estate_context_sha256: str,
    sections: tuple[EvidenceSection, ...],
) -> str:
    payload = {
        "schema_version": 1,
        "workflow_id": str(workflow_id),
        "twin_snapshot_id": str(twin_snapshot_id),
        "estate_context_sha256": estate_context_sha256,
        "sections": [
            {
                "name": item.name,
                "evidence_ref_id": str(item.evidence_ref_id),
                "sha256": item.sha256,
                "execution_mode": item.execution_mode.value,
            }
            for item in sorted(sections, key=lambda item: item.name)
        ],
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def assemble_evidence_bundle(
    *,
    workflow_id: UUID,
    twin_snapshot_id: UUID,
    estate_context_sha256: str,
    sections: tuple[EvidenceSection, ...],
) -> EvidenceBundle:
    ordered = tuple(sorted(sections, key=lambda item: item.name))
    digest = evidence_bundle_digest(
        workflow_id=workflow_id,
        twin_snapshot_id=twin_snapshot_id,
        estate_context_sha256=estate_context_sha256,
        sections=ordered,
    )
    return EvidenceBundle(
        workflow_id=workflow_id,
        twin_snapshot_id=twin_snapshot_id,
        estate_context_sha256=estate_context_sha256,
        sections=ordered,
        bundle_sha256=digest,
    )


def referenced_digest_mismatch(
    sections: tuple[EvidenceSection, ...],
    expected_by_name: dict[str, str],
) -> tuple[str, ...]:
    mismatched: list[str] = []
    for item in sections:
        expected = expected_by_name.get(item.name)
        if expected is not None and expected != item.sha256:
            mismatched.append(item.name)
    return tuple(mismatched)


def missing_required_sections(sections: tuple[EvidenceSection, ...]) -> tuple[str, ...]:
    present = {item.name for item in sections}
    return tuple(name for name in REQUIRED_EVIDENCE_SECTIONS if name not in present)


__all__ = [
    "assemble_evidence_bundle",
    "evidence_bundle_digest",
    "missing_required_sections",
    "referenced_digest_mismatch",
]
