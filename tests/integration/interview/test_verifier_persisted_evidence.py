from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.interview import build_interview_stack
from aide.app.supervisor import InterviewResult
from aide.auth.grants import GrantAuthorizer
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.enums import TargetEnv
from aide.domain.identity import canonical_json_bytes
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef, Role
from aide.domain.states import WorkflowState
from aide.domain.twin import (
    EvidenceReference,
    SourceAuthorityRef,
    TwinAssetKind,
    TwinObservation,
    TwinObservationKind,
    TwinSnapshot,
)
from aide.domain.verification import VerifierReasonCode, VerifierVerdict
from aide.persistence.repositories import ArtifactRepository, WorkflowRepository
from aide.persistence.twin import TwinRepository
from aide.repair.diff import sha256_text
from aide.twin.identity import AssetCapture
from aide.twin.snapshot import build_twin_snapshot
from aide.verification.evaluate import evaluate_verifier

NOW = datetime(2026, 9, 15, 12)
AUTHORITY = SourceAuthorityRef(
    authority_id="snowflake_ro",
    contract_version="1.0.0",
    scope=("VANTARA_RAW",),
)
LLM_AUTHORITY = SourceAuthorityRef(
    authority_id="llm",
    contract_version="1.0.0",
    scope=("VANTARA_RAW",),
)


def _digest(body: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _wall_clock() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _result(workflow_id: UUID, snapshot: TwinSnapshot) -> InterviewResult:
    principal = PrincipalRef(
        principal_id=workflow_id,
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=workflow_id,
    )
    grants = GrantAuthorizer().authorize(
        principal,
        frozenset({PermissionLevel.READ}),
        target_environment=TargetEnv.DEV,
        decided_at=NOW,
    )
    return InterviewResult(
        workflow_id=workflow_id,
        principal=principal,
        grants=grants,
        twin_snapshot=snapshot,
        estate_context_sha256=sha256_text("estate"),
        extra={"typed_evidence": {}},
    )


async def _pin_invoice_workflow(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, TwinSnapshot, UUID]:
    evidence = EvidenceReference(
        evidence_ref_id=uuid4(),
        evidence_type="snowflake.metadata",
        media_type="application/json",
        sha256="a" * 64,
        size_bytes=100,
        execution_mode=ExecutionMode.MOCK,
        source_authority=AUTHORITY,
        producer_operation_key="a" * 64,
        created_at=NOW,
    )
    async with session_factory() as session, session.begin():
        twins = TwinRepository(session)
        workflow = await WorkflowRepository(session).add(state=WorkflowState.PLANNING)
        await twins.add_evidence_reference(evidence)
        asset = await twins.capture_asset(
            AssetCapture(
                kind=TwinAssetKind.DATASET,
                source_authority=AUTHORITY,
                native_key=None,
                canonical_locator=("VANTARA_RAW", "BILLING", "INVOICES"),
                incarnation=1,
                platform_type="snowflake.table",
                attributes={"columns": 3},
                observed_at=NOW,
                evidence_ref_id=evidence.evidence_ref_id,
            )
        )
        snapshot = build_twin_snapshot(
            assets=(asset,),
            relationships=(),
            observations=(),
            evidence_references=(evidence,),
            captured_at=NOW,
            capture_cutoff=NOW,
        )
        await twins.add_snapshot(snapshot)
        await twins.pin_snapshot(
            workflow_id=workflow.workflow_id, twin_snapshot_id=snapshot.twin_snapshot_id
        )
        return workflow.workflow_id, snapshot, asset.asset_id


async def _persist_evidence(
    session: AsyncSession,
    *,
    workflow_id: UUID,
    evidence_type: str,
    body: dict[str, Any],
    execution_mode: ExecutionMode,
    artifact_sha256: str | None = None,
    reference_sha256: str | None = None,
) -> EvidenceReference:
    actual = _digest(body)
    artifacts = ArtifactRepository(session)
    version = await artifacts.next_version(workflow_id, evidence_type)
    artifact = await artifacts.add(
        workflow_id=workflow_id,
        task_id=None,
        artifact_type=evidence_type,
        version=version,
        schema_version=1,
        sha256=artifact_sha256 or actual,
        provenance=ArtifactProvenance(
            execution_mode=execution_mode,
            connector_id=None,
            connector_version=None,
            capability_id="supervisor",
            capability_version=1,
            operation_idempotency_key=actual,
            resolved_input_digest=actual,
        ),
        body=body,
    )
    reference = EvidenceReference(
        evidence_ref_id=uuid4(),
        evidence_type=evidence_type,
        artifact_id=artifact.artifact_id,
        media_type="application/json",
        sha256=reference_sha256 or actual,
        size_bytes=len(canonical_json_bytes(body)),
        execution_mode=execution_mode,
        source_authority=AUTHORITY,
        producer_operation_key=actual,
        created_at=NOW,
    )
    await TwinRepository(session).add_evidence_reference(reference)
    return reference


async def _persist_reference_only(
    session: AsyncSession,
    *,
    evidence_type: str,
    digest: str,
    execution_mode: ExecutionMode,
) -> EvidenceReference:
    reference = EvidenceReference(
        evidence_ref_id=uuid4(),
        evidence_type=evidence_type,
        media_type="application/json",
        sha256=digest,
        size_bytes=32,
        execution_mode=execution_mode,
        source_authority=AUTHORITY,
        producer_operation_key=digest,
        created_at=NOW,
    )
    await TwinRepository(session).add_evidence_reference(reference)
    return reference


def _bind(result: InterviewResult, name: str, reference: EvidenceReference) -> None:
    typed = result.extra.setdefault("typed_evidence", {})
    typed[name] = {
        "evidence_ref_id": str(reference.evidence_ref_id),
        "sha256": reference.sha256,
    }


@pytest.mark.asyncio
async def test_mixed_persisted_provenance_fails_verifier(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, _asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    async with session_factory() as session, session.begin():
        mock_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="dbt_tests",
            body={"ok": True},
            execution_mode=ExecutionMode.MOCK,
        )
        real_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="dbt_execution",
            body={"ok": True, "mode": "real"},
            execution_mode=ExecutionMode.REAL,
        )
    _bind(result, "dbt_tests", mock_ref)
    _bind(result, "dbt_execution", real_ref)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    modes = {item.execution_mode for item in pack.evidence}
    assert ExecutionMode.MOCK in modes
    assert ExecutionMode.REAL in modes
    assert pack.require_real_chain is False
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.PROVENANCE_MIX.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_real_workflow_fails_when_required_evidence_is_mock(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, _asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    async with session_factory() as session, session.begin():
        mock_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="quality_results",
            body={"passed": True},
            execution_mode=ExecutionMode.MOCK,
        )
    _bind(result, "quality_results", mock_ref)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    supervisor._execution_mode = ExecutionMode.REAL
    pack = await supervisor._verifier_pack(result)
    assert pack.require_real_chain is True
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.PROVENANCE_MIX.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_persisted_fresh_authoritative_drift_checks_pass(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    drift_digest = sha256_text("fresh-drift")
    async with session_factory() as session, session.begin():
        reference = await _persist_reference_only(
            session,
            evidence_type="schema_drift",
            digest=drift_digest,
            execution_mode=ExecutionMode.MOCK,
        )
        await TwinRepository(session).add_observation(
            TwinObservation(
                observation_id=uuid4(),
                subject_asset_id=asset_id,
                kind=TwinObservationKind.DRIFT,
                source_authority=AUTHORITY,
                value={"authoritative": True, "from_column": "INVOICE_STATUS"},
                observed_at=_wall_clock() - timedelta(minutes=1),
                fresh_until=_wall_clock() + timedelta(hours=1),
                confidence=1,
                evidence_ref_id=reference.evidence_ref_id,
            )
        )
    _bind(result, "schema_drift", reference)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    assert pack.drift_evidence_ref_id == reference.evidence_ref_id
    assert pack.drift_stale is False
    assert pack.drift_authoritative is True
    by_id = {item.check_id: item for item in evaluate_verifier(pack).checks}
    assert by_id["drift_not_stale"].passed
    assert by_id["drift_authoritative"].passed
    assert by_id["drift_digest_identity"].passed


@pytest.mark.asyncio
async def test_persisted_expired_drift_fails(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    drift_digest = sha256_text("expired-drift")
    async with session_factory() as session, session.begin():
        reference = await _persist_reference_only(
            session,
            evidence_type="schema_drift",
            digest=drift_digest,
            execution_mode=ExecutionMode.MOCK,
        )
        await TwinRepository(session).add_observation(
            TwinObservation(
                observation_id=uuid4(),
                subject_asset_id=asset_id,
                kind=TwinObservationKind.DRIFT,
                source_authority=AUTHORITY,
                value={"authoritative": True},
                observed_at=_wall_clock() - timedelta(hours=2),
                fresh_until=_wall_clock() - timedelta(minutes=1),
                confidence=1,
                evidence_ref_id=reference.evidence_ref_id,
            )
        )
    _bind(result, "schema_drift", reference)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    assert pack.drift_stale is True
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.EVIDENCE_STALE.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_wrong_persisted_drift_evidence_identity_fails(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    async with session_factory() as session, session.begin():
        observed = await _persist_reference_only(
            session,
            evidence_type="schema_drift",
            digest=sha256_text("observed"),
            execution_mode=ExecutionMode.MOCK,
        )
        claimed = await _persist_reference_only(
            session,
            evidence_type="schema_drift",
            digest=sha256_text("claimed"),
            execution_mode=ExecutionMode.MOCK,
        )
        await TwinRepository(session).add_observation(
            TwinObservation(
                observation_id=uuid4(),
                subject_asset_id=asset_id,
                kind=TwinObservationKind.DRIFT,
                source_authority=AUTHORITY,
                value={"authoritative": True},
                observed_at=_wall_clock() - timedelta(minutes=1),
                fresh_until=_wall_clock() + timedelta(hours=1),
                confidence=1,
                evidence_ref_id=observed.evidence_ref_id,
            )
        )
    _bind(result, "schema_drift", claimed)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    assert pack.drift_evidence_ref_id == observed.evidence_ref_id
    schema_item = next(item for item in pack.evidence if item.evidence_type == "schema_drift")
    assert schema_item.evidence_ref_id == claimed.evidence_ref_id
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.DIGEST_MISMATCH.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_non_authoritative_persisted_drift_fails(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    async with session_factory() as session, session.begin():
        reference = await _persist_reference_only(
            session,
            evidence_type="schema_drift",
            digest=sha256_text("llm-drift"),
            execution_mode=ExecutionMode.MOCK,
        )
        await TwinRepository(session).add_observation(
            TwinObservation(
                observation_id=uuid4(),
                subject_asset_id=asset_id,
                kind=TwinObservationKind.DRIFT,
                source_authority=LLM_AUTHORITY,
                value={"authoritative": False},
                observed_at=_wall_clock() - timedelta(minutes=1),
                fresh_until=_wall_clock() + timedelta(hours=1),
                confidence=1,
                evidence_ref_id=reference.evidence_ref_id,
            )
        )
    _bind(result, "schema_drift", reference)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    assert pack.drift_authoritative is False
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.OUT_OF_SCOPE.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_wrong_evidence_reference_digest_fails(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, _asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    before = sha256_text("before-sql")
    after = sha256_text("after-sql")
    async with session_factory() as session, session.begin():
        proposal = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="repair_proposal",
            body={
                "preimage_sha256": before,
                "patched_sha256": after,
                "from_column": "INVOICE_STATUS",
                "to_column": "STATUS",
            },
            execution_mode=ExecutionMode.MOCK,
        )
        application = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="repair_application",
            body={"applied": True, "postimage_sha256": after, "preimage_sha256": before},
            execution_mode=ExecutionMode.MOCK,
        )
        before_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="before_artifact_hash",
            body={"sha256": before},
            execution_mode=ExecutionMode.MOCK,
        )
        after_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="after_artifact_hash",
            body={"sha256": after},
            execution_mode=ExecutionMode.MOCK,
        )
    _bind(result, "repair_proposal", proposal)
    _bind(result, "repair_application", application)
    _bind(result, "before_artifact_hash", before_ref)
    _bind(result, "after_artifact_hash", after_ref)
    result.extra["typed_evidence"]["before_artifact_hash"]["sha256"] = sha256_text("catalog-wrong")
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    before_item = next(
        item for item in pack.evidence if item.evidence_type == "before_artifact_hash"
    )
    assert before_item.sha256 == before_ref.sha256
    assert before_item.digest_mismatch is True
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.DIGEST_MISMATCH.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_wrong_artifact_body_digest_fails(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, _asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    before = sha256_text("before-sql")
    after = sha256_text("after-sql")
    async with session_factory() as session, session.begin():
        proposal = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="repair_proposal",
            body={
                "preimage_sha256": before,
                "patched_sha256": after,
                "from_column": "INVOICE_STATUS",
                "to_column": "STATUS",
            },
            execution_mode=ExecutionMode.MOCK,
        )
        application = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="repair_application",
            body={"applied": True, "postimage_sha256": after, "preimage_sha256": before},
            execution_mode=ExecutionMode.MOCK,
        )
        before_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="before_artifact_hash",
            body={"sha256": before},
            execution_mode=ExecutionMode.MOCK,
            artifact_sha256="b" * 64,
        )
        after_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="after_artifact_hash",
            body={"sha256": after},
            execution_mode=ExecutionMode.MOCK,
        )
    _bind(result, "repair_proposal", proposal)
    _bind(result, "repair_application", application)
    _bind(result, "before_artifact_hash", before_ref)
    _bind(result, "after_artifact_hash", after_ref)
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    before_item = next(
        item for item in pack.evidence if item.evidence_type == "before_artifact_hash"
    )
    assert before_item.digest_mismatch is True
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.DIGEST_MISMATCH.value in verdict.reason_codes


@pytest.mark.asyncio
async def test_persisted_claimed_artifact_hash_mismatch_fails(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    workflow_id, snapshot, _asset_id = await _pin_invoice_workflow(session_factory)
    result = _result(workflow_id, snapshot)
    before = sha256_text("before-sql")
    after = sha256_text("after-sql")
    other = sha256_text("other-sql")
    async with session_factory() as session, session.begin():
        proposal = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="repair_proposal",
            body={
                "preimage_sha256": before,
                "patched_sha256": after,
                "from_column": "INVOICE_STATUS",
                "to_column": "STATUS",
            },
            execution_mode=ExecutionMode.MOCK,
        )
        application = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="repair_application",
            body={"applied": True, "postimage_sha256": after, "preimage_sha256": before},
            execution_mode=ExecutionMode.MOCK,
        )
        before_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="before_artifact_hash",
            body={"sha256": other},
            execution_mode=ExecutionMode.MOCK,
        )
        after_ref = await _persist_evidence(
            session,
            workflow_id=workflow_id,
            evidence_type="after_artifact_hash",
            body={"sha256": after},
            execution_mode=ExecutionMode.MOCK,
        )
    _bind(result, "repair_proposal", proposal)
    _bind(result, "repair_application", application)
    _bind(result, "before_artifact_hash", before_ref)
    _bind(result, "after_artifact_hash", after_ref)
    result.before_artifact_hash = other
    result.after_artifact_hash = after
    supervisor = build_interview_stack(session_factory, work_root=tmp_path)
    pack = await supervisor._verifier_pack(result)
    assert pack.before_artifact_hash == before
    before_item = next(
        item for item in pack.evidence if item.evidence_type == "before_artifact_hash"
    )
    assert before_item.sha256 == before_ref.sha256
    assert before_item.claimed_sha256 == other
    verdict = evaluate_verifier(pack)
    assert verdict.verdict is VerifierVerdict.FAIL
    assert VerifierReasonCode.DIGEST_MISMATCH.value in verdict.reason_codes
