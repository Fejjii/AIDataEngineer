from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.domain.states import WorkflowState
from aide.domain.twin import EvidenceReference, SourceAuthorityRef, TwinAssetKind
from aide.persistence.repositories import WorkflowRepository
from aide.persistence.twin import TwinRepository
from aide.twin.identity import AssetCapture, RenameContinuity, TwinIdentityError
from aide.twin.snapshot import build_twin_snapshot

NOW = datetime(2026, 9, 14, 12)
AUTHORITY = SourceAuthorityRef(
    authority_id="snowflake_ro",
    contract_version="1.0",
    scope=("VANTARA_RAW",),
)


def _evidence() -> EvidenceReference:
    return EvidenceReference(
        evidence_ref_id=uuid4(),
        evidence_type="snowflake.metadata",
        media_type="application/json",
        sha256="a" * 64,
        size_bytes=100,
        execution_mode="REAL",
        source_authority=AUTHORITY,
        created_at=NOW,
    )


def _capture(
    evidence: EvidenceReference,
    *,
    locator: tuple[str, ...] = ("VANTARA_RAW", "BILLING", "INVOICES"),
    columns: int = 5,
) -> AssetCapture:
    return AssetCapture(
        kind=TwinAssetKind.DATASET,
        source_authority=AUTHORITY,
        native_key=None,
        canonical_locator=locator,
        platform_type="snowflake.table",
        attributes={"columns": columns},
        observed_at=NOW,
        evidence_ref_id=evidence.evidence_ref_id,
    )


async def test_asset_versions_rename_recreation_snapshot_pin_and_immutability(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    evidence = _evidence()
    async with session_factory() as session, session.begin():
        repository = TwinRepository(session)
        workflow = await WorkflowRepository(session).add(state=WorkflowState.PLANNING)
        await repository.add_evidence_reference(evidence)
        first = await repository.capture_asset(_capture(evidence))
        repeated = await repository.capture_asset(_capture(evidence))
        changed = await repository.capture_asset(_capture(evidence, columns=6))
        recreated = await repository.capture_asset(_capture(evidence, columns=6), incarnation=2)
        renamed = await repository.capture_asset(
            _capture(
                evidence,
                locator=("VANTARA_RAW", "BILLING", "BILLING_INVOICES"),
                columns=6,
            ),
            rename_continuity=RenameContinuity(
                asset_id=changed.asset_id,
                evidence_ref_id=evidence.evidence_ref_id,
                source_authority=AUTHORITY,
            ),
        )
        snapshot = build_twin_snapshot(
            assets=(first,),
            relationships=(),
            observations=(),
            evidence_references=(evidence,),
            captured_at=NOW + timedelta(minutes=1),
            capture_cutoff=NOW + timedelta(minutes=1),
        )
        await repository.add_snapshot(snapshot)
        await repository.pin_snapshot(
            workflow_id=workflow.workflow_id,
            twin_snapshot_id=snapshot.twin_snapshot_id,
        )

    assert repeated == first
    assert changed.asset_id == first.asset_id
    assert changed.asset_version == 2
    assert recreated.asset_id != first.asset_id
    assert renamed.asset_id == first.asset_id
    assert renamed.asset_version == 3

    async with session_factory() as session:
        with pytest.raises(DBAPIError, match="published Twin records are immutable"):
            await session.execute(
                text("UPDATE twin_assets SET platform_type = 'changed' WHERE asset_id = :asset_id"),
                {"asset_id": first.asset_id},
            )
            await session.commit()
        await session.rollback()

    async with session_factory() as session:
        records = await TwinRepository(session).pinned_snapshot(workflow.workflow_id)
    assert records.snapshot.twin_snapshot_id == snapshot.twin_snapshot_id
    assert records.assets == (first,)

    other_snapshot = build_twin_snapshot(
        assets=(changed,),
        relationships=(),
        observations=(),
        evidence_references=(evidence,),
        captured_at=NOW + timedelta(minutes=2),
        capture_cutoff=NOW + timedelta(minutes=2),
    )
    async with session_factory() as session, session.begin():
        repository = TwinRepository(session)
        await repository.add_snapshot(other_snapshot)
        with pytest.raises(TwinIdentityError, match="already pins"):
            await repository.pin_snapshot(
                workflow_id=workflow.workflow_id,
                twin_snapshot_id=other_snapshot.twin_snapshot_id,
            )
