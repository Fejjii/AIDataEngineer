from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.evidence import validate_persisted_evidence
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.identity import canonical_json_bytes
from aide.domain.states import WorkflowState
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, EvidenceSection
from aide.persistence.repositories import ArtifactRepository, WorkflowRepository
from aide.repair.diff import sha256_text
from aide.verification.bundle import assemble_evidence_bundle, evidence_bundle_digest

NOW_PROVENANCE = ArtifactProvenance(
    execution_mode=ExecutionMode.MOCK,
    connector_id=None,
    connector_version=None,
    capability_id="supervisor",
    capability_version=1,
    operation_idempotency_key="a" * 64,
    resolved_input_digest="b" * 64,
)


def _digest(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


async def _new_workflow(session_factory: async_sessionmaker[AsyncSession]) -> UUID:
    async with session_factory() as session, session.begin():
        workflow = await WorkflowRepository(session).add(state=WorkflowState.PLANNING)
        return workflow.workflow_id


async def _add_artifact(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    artifact_type: str,
    body: dict[str, Any],
    sha256: str | None = None,
) -> None:
    artifacts = ArtifactRepository(session)
    version = await artifacts.next_version(workflow_id, artifact_type)
    await artifacts.add(
        workflow_id=workflow_id,
        task_id=None,
        artifact_type=artifact_type,
        version=version,
        schema_version=1,
        sha256=sha256 or _digest(body),
        provenance=NOW_PROVENANCE,
        body=body,
    )


async def _persist_valid_bundle(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_id: UUID | None = None,
    skip_section: str | None = None,
    section_digest_override: dict[str, str] | None = None,
    bundle_sha_override: str | None = None,
    bundle_workflow_id: UUID | None = None,
    bundle_snapshot_id: UUID | None = None,
) -> tuple[UUID, str]:
    workflow_id = workflow_id or await _new_workflow(session_factory)
    snapshot_id = bundle_snapshot_id or uuid4()
    estate = sha256_text("estate")
    section_bodies = {name: {"section": name, "ok": True} for name in REQUIRED_EVIDENCE_SECTIONS}
    async with session_factory() as session, session.begin():
        sections: list[EvidenceSection] = []
        for name in REQUIRED_EVIDENCE_SECTIONS:
            body = section_bodies[name]
            if section_digest_override is None:
                digest = _digest(body)
            else:
                digest = section_digest_override.get(name, _digest(body))
            if name != skip_section:
                await _add_artifact(session, workflow_id=workflow_id, artifact_type=name, body=body)
            sections.append(
                EvidenceSection(
                    name=name,
                    evidence_ref_id=uuid4(),
                    sha256=digest,
                    execution_mode=ExecutionMode.MOCK,
                )
            )
        identity_workflow = bundle_workflow_id or workflow_id
        bundle = assemble_evidence_bundle(
            workflow_id=identity_workflow,
            twin_snapshot_id=snapshot_id,
            estate_context_sha256=estate,
            sections=tuple(sections),
        )
        body = bundle.model_dump(mode="json")
        if bundle_sha_override is not None:
            body["bundle_sha256"] = bundle_sha_override
        await _add_artifact(
            session,
            workflow_id=workflow_id,
            artifact_type="evidence_bundle",
            body=body,
        )
    recomputed = evidence_bundle_digest(
        workflow_id=identity_workflow,
        twin_snapshot_id=snapshot_id,
        estate_context_sha256=estate,
        sections=tuple(sections),
    )
    return workflow_id, recomputed


@pytest.mark.asyncio
async def test_persisted_bundle_digest_matches_recomputed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(session_factory)
    completeness, persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete
    assert persisted == digest
    assert not completeness.digest_mismatches
    assert not completeness.missing_sections


@pytest.mark.asyncio
async def test_tampered_bundle_sha256_fails_at20(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(session_factory, bundle_sha_override="0" * 64)
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete is False
    assert "evidence_bundle" in completeness.digest_mismatches


@pytest.mark.asyncio
async def test_tampered_section_digest_fails_at20(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(
        session_factory, section_digest_override={"plan": "c" * 64}
    )
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete is False
    assert "plan" in completeness.digest_mismatches


@pytest.mark.asyncio
async def test_missing_section_artifact_fails_at20(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(session_factory, skip_section="dbt_tests")
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=digest
    )
    assert completeness.complete is False
    assert "dbt_tests" in completeness.missing_sections


@pytest.mark.asyncio
async def test_wrong_workflow_binding_fails_at20(
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
async def test_wrong_snapshot_binding_fails_at20(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id = await _new_workflow(session_factory)
    _wid, original = await _persist_valid_bundle(session_factory, workflow_id=workflow_id)
    completeness, _persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256=original
    )
    assert completeness.complete
    other_snapshot = uuid4()
    async with session_factory() as session, session.begin():
        artifacts = await ArtifactRepository(session).list_for_workflow(workflow_id)
        bundle_row = [row for row in artifacts if row.artifact_type == "evidence_bundle"][-1]
        assert bundle_row.body is not None
        body = dict(bundle_row.body)
        body["twin_snapshot_id"] = str(other_snapshot)
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
    assert (
        "evidence_bundle" in completeness.digest_mismatches
        or "stored_benchmark_digest" in completeness.digest_mismatches
    )


@pytest.mark.asyncio
async def test_wrong_claimed_extra_digest_is_not_authority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workflow_id, digest = await _persist_valid_bundle(session_factory)
    completeness, persisted = await validate_persisted_evidence(
        session_factory, workflow_id, claimed_bundle_sha256="d" * 64
    )
    assert persisted == digest
    assert completeness.complete is False
    assert "stored_benchmark_digest" in completeness.digest_mismatches
