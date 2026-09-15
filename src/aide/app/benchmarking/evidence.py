"""Validate the immutable evidence-bundle manifest against persisted artifacts."""

from __future__ import annotations

import hashlib
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.domain.artifacts import ExecutionMode
from aide.domain.benchmark import EvidenceCompleteness
from aide.domain.identity import canonical_json_bytes
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, EvidenceBundle
from aide.persistence.repositories import ArtifactRepository
from aide.persistence.twin import TwinRepository
from aide.verification.bundle import evidence_bundle_digest, missing_required_sections


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
    mismatches: list[str] = []
    if expected_by_name is not None:
        for item in bundle.sections:
            expected = expected_by_name.get(item.name)
            if expected is not None and expected != item.sha256:
                mismatches.append(item.name)
    required = len(REQUIRED_EVIDENCE_SECTIONS)
    present_required = required - len(missing)
    pct = int((present_required * 100) / required) if required else 0
    return EvidenceCompleteness(
        required_sections=REQUIRED_EVIDENCE_SECTIONS,
        present_sections=present,
        missing_sections=missing,
        digest_mismatches=tuple(mismatches),
        completeness_pct=pct,
        complete=not missing and not mismatches,
    )


def _failed(
    *,
    present: tuple[str, ...] = (),
    missing: tuple[str, ...] = REQUIRED_EVIDENCE_SECTIONS,
    mismatches: tuple[str, ...] = (),
) -> tuple[EvidenceCompleteness, str | None]:
    required = len(REQUIRED_EVIDENCE_SECTIONS)
    present_required = len([name for name in REQUIRED_EVIDENCE_SECTIONS if name in present])
    pct = int((present_required * 100) / required) if required else 0
    return (
        EvidenceCompleteness(
            required_sections=REQUIRED_EVIDENCE_SECTIONS,
            present_sections=present,
            missing_sections=missing,
            digest_mismatches=mismatches,
            completeness_pct=pct,
            complete=False,
        ),
        None,
    )


async def validate_persisted_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    workflow_id: UUID,
    *,
    claimed_bundle_sha256: str | None = None,
) -> tuple[EvidenceCompleteness, str | None]:
    """Recompute the persisted EvidenceBundle digest. Do not trust result.extra."""
    async with session_factory() as session:
        artifacts = await ArtifactRepository(session).list_for_workflow(workflow_id)
        twins = TwinRepository(session)
        latest_digest: dict[str, str] = {}
        latest_body: dict[str, dict[str, object] | None] = {}
        mismatches: list[str] = []
        for row in artifacts:
            if row.body is None:
                continue
            recomputed = hashlib.sha256(canonical_json_bytes(row.body)).hexdigest()
            if recomputed != row.sha256 and row.artifact_type not in mismatches:
                mismatches.append(row.artifact_type)
            latest_digest[row.artifact_type] = recomputed
            latest_body[row.artifact_type] = row.body
        bundle_body = latest_body.get("evidence_bundle")
        if not isinstance(bundle_body, dict):
            return _failed(mismatches=tuple(mismatches) + ("evidence_bundle",))
        try:
            bundle = EvidenceBundle.model_validate(bundle_body)
        except ValidationError:
            return _failed(
                present=tuple(latest_digest),
                missing=tuple(
                    name for name in REQUIRED_EVIDENCE_SECTIONS if name not in latest_digest
                ),
                mismatches=tuple(dict.fromkeys([*mismatches, "evidence_bundle"])),
            )
        if bundle.workflow_id != workflow_id:
            mismatches.append("workflow_id")
        modes = {item.execution_mode for item in bundle.sections}
        if ExecutionMode.REAL in modes and ExecutionMode.MOCK in modes:
            mismatches.append("execution_mode")
        recomputed_bundle = evidence_bundle_digest(
            workflow_id=bundle.workflow_id,
            twin_snapshot_id=bundle.twin_snapshot_id,
            estate_context_sha256=bundle.estate_context_sha256,
            sections=bundle.sections,
        )
        if recomputed_bundle != bundle.bundle_sha256 and "evidence_bundle" not in mismatches:
            mismatches.append("evidence_bundle")
        if claimed_bundle_sha256 is None or claimed_bundle_sha256 != recomputed_bundle:
            mismatches.append("stored_benchmark_digest")
        missing = list(missing_required_sections(bundle.sections))
        for section in bundle.sections:
            reference = await twins.get_evidence_reference(section.evidence_ref_id)
            artifact_digest = latest_digest.get(section.name)
            if reference is None and artifact_digest is None:
                if section.name not in missing:
                    missing.append(section.name)
                continue
            if (
                reference is not None
                and reference.execution_mode != section.execution_mode
                and "execution_mode" not in mismatches
            ):
                mismatches.append("execution_mode")
            if (
                reference is not None
                and reference.sha256 != section.sha256
                and section.name not in mismatches
            ):
                mismatches.append(section.name)
            if (
                artifact_digest is not None
                and artifact_digest != section.sha256
                and section.name not in mismatches
            ):
                mismatches.append(section.name)
    present = tuple(item.name for item in bundle.sections)
    required = len(REQUIRED_EVIDENCE_SECTIONS)
    present_required = required - len(missing)
    pct = int((present_required * 100) / required) if required else 0
    unique_mismatches = tuple(dict.fromkeys(mismatches))
    complete = not missing and not unique_mismatches
    return (
        EvidenceCompleteness(
            required_sections=REQUIRED_EVIDENCE_SECTIONS,
            present_sections=present,
            missing_sections=tuple(missing),
            digest_mismatches=unique_mismatches,
            completeness_pct=pct,
            complete=complete,
        ),
        recomputed_bundle if complete or recomputed_bundle else None,
    )


__all__ = ["completeness_from_bundle", "validate_persisted_evidence"]
