"""Evidence tampering must fail completeness and Independent Verifier checks."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.interview.test_evidence_bundle_persistence import (
    _digest,
    _persist_valid_bundle,
)
from tests.unit.verification.test_verifier import _pack

from aide.app.benchmarking.evidence import validate_persisted_evidence
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.verification import EvidenceBundle, VerifierVerdict
from aide.persistence.repositories import ArtifactRepository
from aide.repair.diff import sha256_text
from aide.verification.bundle import assemble_evidence_bundle
from aide.verification.evaluate import evaluate_verifier

NOW_PROVENANCE = ArtifactProvenance(
    execution_mode=ExecutionMode.MOCK,
    connector_id=None,
    connector_version=None,
    capability_id="supervisor",
    capability_version=1,
    operation_idempotency_key="a" * 64,
    resolved_input_digest="b" * 64,
)


@pytest.mark.asyncio
async def test_e_tm_section_digest_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(
        session_factory, section_digest_override={"schema_drift": "c" * 64}
    )
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete is False
    assert "schema_drift" in completeness.digest_mismatches


@pytest.mark.asyncio
async def test_e_tm_bundle_digest_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(session_factory, bundle_sha_override="0" * 64)
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete is False
    assert "evidence_bundle" in completeness.digest_mismatches


@pytest.mark.asyncio
async def test_e_tm_workflow_binding_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(session_factory, bundle_workflow_id=uuid4())
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete is False
    assert (
        "workflow_id" in completeness.digest_mismatches
        or "evidence_bundle" in completeness.digest_mismatches
    )


@pytest.mark.asyncio
async def test_e_tm_snapshot_binding_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, original = await _persist_valid_bundle(session_factory)
    async with session_factory() as session, session.begin():
        artifacts = await ArtifactRepository(session).list_for_workflow(workflow_id)
        bundle_row = [row for row in artifacts if row.artifact_type == "evidence_bundle"][-1]
        assert bundle_row.body is not None
        body = dict(bundle_row.body)
        body["twin_snapshot_id"] = str(uuid4())
        version = await ArtifactRepository(session).next_version(workflow_id, "evidence_bundle")
        await ArtifactRepository(session).add(
            workflow_id=workflow_id,
            task_id=None,
            artifact_type="evidence_bundle",
            version=version,
            schema_version=1,
            sha256=_digest(body),
            provenance=NOW_PROVENANCE,
            body=body,
        )
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=original
    )
    assert completeness.complete is False


@pytest.mark.asyncio
async def test_e_tm_execution_mode_rehashed_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, _original = await _persist_valid_bundle(session_factory)
    async with session_factory() as session, session.begin():
        artifacts = await ArtifactRepository(session).list_for_workflow(workflow_id)
        bundle_row = [row for row in artifacts if row.artifact_type == "evidence_bundle"][-1]
        assert bundle_row.body is not None
        bundle = EvidenceBundle.model_validate(bundle_row.body)
        sections = tuple(
            item.model_copy(update={"execution_mode": ExecutionMode.REAL})
            if item.name == "plan"
            else item
            for item in bundle.sections
        )
        tampered = assemble_evidence_bundle(
            workflow_id=bundle.workflow_id,
            twin_snapshot_id=bundle.twin_snapshot_id,
            estate_context_sha256=bundle.estate_context_sha256,
            sections=sections,
        )
        body = tampered.model_dump(mode="json")
        version = await ArtifactRepository(session).next_version(workflow_id, "evidence_bundle")
        await ArtifactRepository(session).add(
            workflow_id=workflow_id,
            task_id=None,
            artifact_type="evidence_bundle",
            version=version,
            schema_version=1,
            sha256=_digest(body),
            provenance=NOW_PROVENANCE,
            body=body,
        )
        claimed = tampered.bundle_sha256
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=claimed
    )
    assert completeness.complete is False
    assert "execution_mode" in completeness.digest_mismatches


def test_e_tm_drift_identity_fails_verifier() -> None:
    result = evaluate_verifier(_pack(drift_evidence_ref_id=uuid4()))
    assert result.verdict is VerifierVerdict.FAIL
    assert "DIGEST_MISMATCH" in result.reason_codes


def test_e_tm_artifact_hash_fails_verifier() -> None:
    result = evaluate_verifier(_pack(before_artifact_hash=sha256_text("tampered")))
    assert result.verdict is VerifierVerdict.FAIL
    assert "DIGEST_MISMATCH" in result.reason_codes
