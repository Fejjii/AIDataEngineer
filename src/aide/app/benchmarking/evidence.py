"""Validate the immutable evidence-bundle manifest against persisted artifacts."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.domain.benchmark import EvidenceCompleteness
from aide.domain.identity import canonical_json_bytes
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, EvidenceBundle
from aide.persistence.repositories import ArtifactRepository
from aide.verification.bundle import missing_required_sections, referenced_digest_mismatch


def completeness_from_bundle(
    bundle: EvidenceBundle | None,
    *,
    expected_by_name: dict[str, str] | None = None,
) -> EvidenceCompleteness:
    if bundle is None:
        return EvidenceCompleteness(
            required_sections=REQUIRED_EVIDENCE_SECTIONS,
            present_sections=(),
            missing_sections=REQUIRED_EVIDENCE_SECTIONS,
            digest_mismatches=(),
            completeness_pct=0,
            complete=False,
        )
    missing = missing_required_sections(bundle.sections)
    present = tuple(item.name for item in bundle.sections)
    mismatches = (
        referenced_digest_mismatch(bundle.sections, expected_by_name)
        if expected_by_name is not None
        else ()
    )
    required = len(REQUIRED_EVIDENCE_SECTIONS)
    present_required = required - len(missing)
    pct = int((present_required * 100) / required) if required else 0
    return EvidenceCompleteness(
        required_sections=REQUIRED_EVIDENCE_SECTIONS,
        present_sections=present,
        missing_sections=missing,
        digest_mismatches=mismatches,
        completeness_pct=pct,
        complete=not missing and not mismatches,
    )


async def validate_persisted_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_id: UUID,
    typed_evidence: dict[str, dict[str, str]],
) -> EvidenceCompleteness:
    """Recompute artifact digests and compare them to the bundle references."""
    async with session_factory() as session:
        artifacts = await ArtifactRepository(session).list_for_workflow(workflow_id)
    latest: dict[str, str] = {}
    mismatches: list[str] = []
    for row in artifacts:
        if row.body is None:
            continue
        recomputed = hashlib.sha256(canonical_json_bytes(row.body)).hexdigest()
        if recomputed != row.sha256:
            mismatches.append(row.artifact_type)
        latest[row.artifact_type] = recomputed
    present = tuple(name for name in REQUIRED_EVIDENCE_SECTIONS if name in typed_evidence)
    missing = tuple(name for name in REQUIRED_EVIDENCE_SECTIONS if name not in typed_evidence)
    for name, payload in typed_evidence.items():
        claimed = payload.get("sha256")
        if (
            claimed is not None
            and name in latest
            and latest[name] != claimed
            and name not in mismatches
        ):
            mismatches.append(name)
    required = len(REQUIRED_EVIDENCE_SECTIONS)
    pct = int(((required - len(missing)) * 100) / required) if required else 0
    return EvidenceCompleteness(
        required_sections=REQUIRED_EVIDENCE_SECTIONS,
        present_sections=present,
        missing_sections=missing,
        digest_mismatches=tuple(mismatches),
        completeness_pct=pct,
        complete=not missing and not mismatches,
    )


__all__ = ["completeness_from_bundle", "validate_persisted_evidence"]
