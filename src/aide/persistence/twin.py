"""PostgreSQL repository for append-only Digital Twin records and snapshots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.artifacts import ExecutionMode
from aide.domain.identity import canonical_json_bytes
from aide.domain.twin import (
    EvidenceReference,
    SourceAuthorityRef,
    TwinAsset,
    TwinAssetKind,
    TwinEnvironment,
    TwinObservation,
    TwinObservationKind,
    TwinRelationship,
    TwinRelationshipKind,
    TwinSnapshot,
)
from aide.persistence.models import (
    EvidenceReferenceModel,
    TwinAssetModel,
    TwinObservationModel,
    TwinRelationshipModel,
    TwinSnapshotAssetModel,
    TwinSnapshotEvidenceModel,
    TwinSnapshotModel,
    TwinSnapshotObservationModel,
    TwinSnapshotRelationshipModel,
    WorkflowTwinSnapshotModel,
)
from aide.twin.identity import (
    AssetCapture,
    ContinuityProofKind,
    RelationshipCapture,
    RenameContinuity,
    TwinIdentityError,
    materialize_asset_version,
    materialize_relationship_version,
)
from aide.twin.records import (
    PendingObservationCapture,
    PendingRelationshipCapture,
    TwinCaptureBatch,
)
from aide.twin.snapshot import snapshot_manifest_payload


@dataclass(frozen=True)
class PersistedCapture:
    assets: tuple[TwinAsset, ...]
    relationships: tuple[TwinRelationship, ...]
    observations: tuple[TwinObservation, ...]
    asset_ids_by_capture_key: dict[str, UUID]


@dataclass(frozen=True)
class TwinSnapshotRecords:
    snapshot: TwinSnapshot
    assets: tuple[TwinAsset, ...]
    relationships: tuple[TwinRelationship, ...]
    observations: tuple[TwinObservation, ...]
    evidence_references: tuple[EvidenceReference, ...]


class TwinRepository:
    """Typed repository; it exposes no update or delete operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_evidence_reference(self, reference: EvidenceReference) -> EvidenceReference:
        existing = await self._session.get(EvidenceReferenceModel, reference.evidence_ref_id)
        if existing is not None:
            persisted = _evidence_from_row(existing)
            if persisted != reference:
                raise TwinIdentityError(
                    f"evidence reference {reference.evidence_ref_id} already has other content"
                )
            return persisted
        row = EvidenceReferenceModel(
            evidence_ref_id=reference.evidence_ref_id,
            evidence_type=reference.evidence_type,
            artifact_id=reference.artifact_id,
            immutable_uri=reference.immutable_uri,
            media_type=reference.media_type,
            sha256=reference.sha256,
            size_bytes=reference.size_bytes,
            execution_mode=reference.execution_mode.value,
            source_authority=reference.source_authority.model_dump(mode="json"),
            source_authority_digest=_authority_digest(reference.source_authority),
            producer_operation_key=reference.producer_operation_key,
            producer_attempt_id=reference.producer_attempt_id,
            created_at=reference.created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return reference

    async def get_evidence_reference(self, evidence_ref_id: UUID) -> EvidenceReference | None:
        row = await self._session.get(EvidenceReferenceModel, evidence_ref_id)
        if row is None:
            return None
        return _evidence_from_row(row)

    async def capture_asset(
        self,
        capture: AssetCapture,
        *,
        rename_continuity: RenameContinuity | None = None,
    ) -> TwinAsset:
        if rename_continuity is not None:
            await self._validate_rename_evidence(capture, rename_continuity)
            rows = await self._asset_rows(rename_continuity.asset_id)
            identity_asset_id: UUID | None = rename_continuity.asset_id
            incarnation = rows[-1].incarnation
        else:
            incarnation = capture.incarnation
            rows = await self._matching_asset_rows(capture)
            identity_asset_id = rows[-1].asset_id if rows else None
        versions = tuple(_asset_from_row(item) for item in rows)
        asset = materialize_asset_version(
            capture,
            existing_versions=versions,
            identity_asset_id=identity_asset_id,
        )
        if versions and asset == versions[-1]:
            return asset
        self._session.add(
            TwinAssetModel(
                asset_id=asset.asset_id,
                asset_version=asset.asset_version,
                kind=asset.kind.value,
                source_authority=asset.source_authority.model_dump(mode="json"),
                source_authority_digest=_authority_digest(asset.source_authority),
                environment=asset.environment.value,
                native_key=asset.native_key,
                canonical_locator=list(asset.canonical_locator),
                canonical_locator_digest=_locator_digest(asset.canonical_locator),
                incarnation=incarnation,
                parent_asset_id=asset.parent_asset_id,
                platform_type=asset.platform_type,
                attributes=asset.attributes,
                first_observed_at=asset.first_observed_at,
                observed_at=asset.observed_at,
                evidence_ref_id=asset.evidence_ref_id,
            )
        )
        await self._session.flush()
        return asset

    async def capture_relationship(self, capture: RelationshipCapture) -> TwinRelationship:
        authority_digest = _authority_digest(capture.source_authority)
        rows = tuple(
            (
                await self._session.scalars(
                    select(TwinRelationshipModel)
                    .where(
                        TwinRelationshipModel.source_authority_digest == authority_digest,
                        TwinRelationshipModel.environment == capture.environment.value,
                        TwinRelationshipModel.kind == capture.kind.value,
                        TwinRelationshipModel.from_asset_id == capture.from_asset_id,
                        TwinRelationshipModel.to_asset_id == capture.to_asset_id,
                    )
                    .order_by(TwinRelationshipModel.relationship_version)
                )
            ).all()
        )
        versions = tuple(_relationship_from_row(item) for item in rows)
        relationship = materialize_relationship_version(capture, existing_versions=versions)
        if versions and relationship == versions[-1]:
            return relationship
        self._session.add(
            TwinRelationshipModel(
                relationship_id=relationship.relationship_id,
                relationship_version=relationship.relationship_version,
                kind=relationship.kind.value,
                from_asset_id=relationship.from_asset_id,
                to_asset_id=relationship.to_asset_id,
                source_authority=relationship.source_authority.model_dump(mode="json"),
                source_authority_digest=authority_digest,
                environment=relationship.environment.value,
                confidence=Decimal(str(relationship.confidence)),
                attributes=relationship.attributes,
                observed_at=relationship.observed_at,
                evidence_ref_id=relationship.evidence_ref_id,
            )
        )
        await self._session.flush()
        return relationship

    async def add_observation(self, observation: TwinObservation) -> TwinObservation:
        existing = await self._session.get(TwinObservationModel, observation.observation_id)
        if existing is not None:
            persisted = _observation_from_row(existing)
            if persisted != observation:
                raise TwinIdentityError(
                    f"observation {observation.observation_id} already has other content"
                )
            return persisted
        self._session.add(
            TwinObservationModel(
                observation_id=observation.observation_id,
                subject_asset_id=observation.subject_asset_id,
                kind=observation.kind.value,
                source_authority=observation.source_authority.model_dump(mode="json"),
                source_authority_digest=_authority_digest(observation.source_authority),
                environment=observation.environment.value,
                value=observation.value,
                observed_at=observation.observed_at,
                effective_at=observation.effective_at,
                fresh_until=observation.fresh_until,
                confidence=Decimal(str(observation.confidence)),
                evidence_ref_id=observation.evidence_ref_id,
            )
        )
        await self._session.flush()
        return observation

    async def persist_capture_batch(self, batch: TwinCaptureBatch) -> PersistedCapture:
        assets_by_key: dict[str, TwinAsset] = {}
        pending = list(batch.assets)
        while pending:
            progressed = False
            for item in tuple(pending):
                parent_id = item.parent_asset_id
                if item.parent_capture_key is not None:
                    parent = assets_by_key.get(item.parent_capture_key)
                    if parent is None:
                        continue
                    parent_id = parent.asset_id
                asset = await self.capture_asset(
                    item.resolved(parent_asset_id=parent_id),
                )
                assets_by_key[item.capture_key] = asset
                pending.remove(item)
                progressed = True
            if not progressed:
                unresolved = sorted(item.capture_key for item in pending)
                raise TwinIdentityError(
                    f"asset capture parent cycle or unresolved key: {unresolved}"
                )
        relationships = tuple(
            [
                await self.capture_relationship(_resolve_relationship(item, assets_by_key))
                for item in batch.relationships
            ]
        )
        observations = tuple(
            [
                await self.add_observation(_resolve_observation(item, assets_by_key))
                for item in batch.observations
            ]
        )
        return PersistedCapture(
            assets=tuple(assets_by_key[item.capture_key] for item in batch.assets),
            relationships=relationships,
            observations=observations,
            asset_ids_by_capture_key={key: value.asset_id for key, value in assets_by_key.items()},
        )

    async def add_snapshot(self, snapshot: TwinSnapshot) -> TwinSnapshot:
        _validate_snapshot_digest(snapshot)
        existing = await self._session.scalar(
            select(TwinSnapshotModel).where(
                TwinSnapshotModel.manifest_sha256 == snapshot.manifest_sha256
            )
        )
        if existing is not None:
            return (await self.load_snapshot(existing.twin_snapshot_id)).snapshot
        row = TwinSnapshotModel(
            twin_snapshot_id=snapshot.twin_snapshot_id,
            schema_version=snapshot.schema_version,
            environment=snapshot.environment.value,
            captured_at=snapshot.captured_at,
            capture_cutoff=snapshot.capture_cutoff,
            source_authorities=[
                item.model_dump(mode="json") for item in snapshot.source_authorities
            ],
            manifest_sha256=snapshot.manifest_sha256,
        )
        self._session.add(row)
        await self._session.flush()
        self._session.add_all(
            [
                TwinSnapshotAssetModel(
                    twin_snapshot_id=snapshot.twin_snapshot_id,
                    asset_id=asset_id,
                    asset_version=version,
                )
                for asset_id, version in snapshot.asset_versions
            ]
        )
        self._session.add_all(
            [
                TwinSnapshotRelationshipModel(
                    twin_snapshot_id=snapshot.twin_snapshot_id,
                    relationship_id=relationship_id,
                    relationship_version=version,
                )
                for relationship_id, version in snapshot.relationship_versions
            ]
        )
        self._session.add_all(
            [
                TwinSnapshotObservationModel(
                    twin_snapshot_id=snapshot.twin_snapshot_id,
                    observation_id=observation_id,
                )
                for observation_id in snapshot.observation_ids
            ]
        )
        self._session.add_all(
            [
                TwinSnapshotEvidenceModel(
                    twin_snapshot_id=snapshot.twin_snapshot_id,
                    evidence_ref_id=evidence_ref_id,
                )
                for evidence_ref_id in snapshot.evidence_reference_ids
            ]
        )
        await self._session.flush()
        return snapshot

    async def pin_snapshot(self, *, workflow_id: UUID, twin_snapshot_id: UUID) -> TwinSnapshot:
        existing = await self._session.get(WorkflowTwinSnapshotModel, workflow_id)
        if existing is not None:
            if existing.twin_snapshot_id != twin_snapshot_id:
                raise TwinIdentityError(
                    f"workflow {workflow_id} already pins another Twin snapshot"
                )
            return (await self.load_snapshot(twin_snapshot_id)).snapshot
        snapshot = await self._session.get(TwinSnapshotModel, twin_snapshot_id)
        if snapshot is None:
            raise LookupError(f"Twin snapshot {twin_snapshot_id} does not exist")
        self._session.add(
            WorkflowTwinSnapshotModel(
                workflow_id=workflow_id,
                twin_snapshot_id=twin_snapshot_id,
            )
        )
        await self._session.flush()
        return (await self.load_snapshot(twin_snapshot_id)).snapshot

    async def pinned_snapshot(self, workflow_id: UUID) -> TwinSnapshotRecords:
        binding = await self._session.get(WorkflowTwinSnapshotModel, workflow_id)
        if binding is None:
            raise LookupError(f"workflow {workflow_id} has no pinned Twin snapshot")
        return await self.load_snapshot(binding.twin_snapshot_id)

    async def list_evidence_for_artifacts(
        self, artifact_ids: tuple[UUID, ...]
    ) -> tuple[EvidenceReference, ...]:
        if not artifact_ids:
            return ()
        rows = (
            await self._session.scalars(
                select(EvidenceReferenceModel).where(
                    EvidenceReferenceModel.artifact_id.in_(artifact_ids)
                )
            )
        ).all()
        return tuple(_evidence_from_row(item) for item in rows)

    async def load_snapshot(self, twin_snapshot_id: UUID) -> TwinSnapshotRecords:
        row = await self._session.get(TwinSnapshotModel, twin_snapshot_id)
        if row is None:
            raise LookupError(f"Twin snapshot {twin_snapshot_id} does not exist")
        asset_members = tuple(
            (
                await self._session.scalars(
                    select(TwinSnapshotAssetModel)
                    .where(TwinSnapshotAssetModel.twin_snapshot_id == twin_snapshot_id)
                    .order_by(TwinSnapshotAssetModel.asset_id)
                )
            ).all()
        )
        relationship_members = tuple(
            (
                await self._session.scalars(
                    select(TwinSnapshotRelationshipModel)
                    .where(TwinSnapshotRelationshipModel.twin_snapshot_id == twin_snapshot_id)
                    .order_by(TwinSnapshotRelationshipModel.relationship_id)
                )
            ).all()
        )
        observation_members = tuple(
            (
                await self._session.scalars(
                    select(TwinSnapshotObservationModel)
                    .where(TwinSnapshotObservationModel.twin_snapshot_id == twin_snapshot_id)
                    .order_by(TwinSnapshotObservationModel.observation_id)
                )
            ).all()
        )
        evidence_members = tuple(
            (
                await self._session.scalars(
                    select(TwinSnapshotEvidenceModel)
                    .where(TwinSnapshotEvidenceModel.twin_snapshot_id == twin_snapshot_id)
                    .order_by(TwinSnapshotEvidenceModel.evidence_ref_id)
                )
            ).all()
        )
        assets = tuple(
            [
                _asset_from_row(await self._require_asset(member.asset_id, member.asset_version))
                for member in asset_members
            ]
        )
        relationships = tuple(
            [
                _relationship_from_row(
                    await self._require_relationship(
                        member.relationship_id, member.relationship_version
                    )
                )
                for member in relationship_members
            ]
        )
        observations = tuple(
            [
                _observation_from_row(await self._require_observation(member.observation_id))
                for member in observation_members
            ]
        )
        evidence = tuple(
            [
                _evidence_from_row(await self._require_evidence(member.evidence_ref_id))
                for member in evidence_members
            ]
        )
        snapshot = TwinSnapshot(
            twin_snapshot_id=row.twin_snapshot_id,
            schema_version=row.schema_version,
            environment=TwinEnvironment(row.environment),
            captured_at=row.captured_at,
            capture_cutoff=row.capture_cutoff,
            asset_versions=tuple((item.asset_id, item.asset_version) for item in asset_members),
            relationship_versions=tuple(
                (item.relationship_id, item.relationship_version) for item in relationship_members
            ),
            observation_ids=tuple(item.observation_id for item in observation_members),
            evidence_reference_ids=tuple(item.evidence_ref_id for item in evidence_members),
            source_authorities=tuple(
                SourceAuthorityRef.model_validate(item) for item in row.source_authorities
            ),
            manifest_sha256=row.manifest_sha256,
        )
        _validate_snapshot_digest(snapshot)
        return TwinSnapshotRecords(
            snapshot=snapshot,
            assets=assets,
            relationships=relationships,
            observations=observations,
            evidence_references=evidence,
        )

    async def _matching_asset_rows(self, capture: AssetCapture) -> tuple[TwinAssetModel, ...]:
        authority_digest = _authority_digest(capture.source_authority)
        statement = select(TwinAssetModel).where(
            TwinAssetModel.source_authority_digest == authority_digest,
            TwinAssetModel.environment == capture.environment.value,
            TwinAssetModel.kind == capture.kind.value,
        )
        if capture.native_key is not None:
            statement = statement.where(TwinAssetModel.native_key == capture.native_key)
        else:
            statement = statement.where(
                TwinAssetModel.native_key.is_(None),
                TwinAssetModel.canonical_locator_digest
                == _locator_digest(capture.canonical_locator),
                TwinAssetModel.incarnation == capture.incarnation,
            )
        rows = await self._session.scalars(statement.order_by(TwinAssetModel.asset_version))
        return tuple(rows.all())

    async def _asset_rows(self, asset_id: UUID) -> tuple[TwinAssetModel, ...]:
        rows = await self._session.scalars(
            select(TwinAssetModel)
            .where(TwinAssetModel.asset_id == asset_id)
            .order_by(TwinAssetModel.asset_version)
        )
        return tuple(rows.all())

    async def _validate_rename_evidence(
        self, capture: AssetCapture, continuity: RenameContinuity
    ) -> None:
        if continuity.source_authority != capture.source_authority:
            raise TwinIdentityError(
                "rename evidence authority does not match captured asset authority"
            )
        evidence = await self._session.get(EvidenceReferenceModel, continuity.evidence_ref_id)
        if evidence is None:
            raise TwinIdentityError("authoritative rename evidence is not persisted")
        if SourceAuthorityRef.model_validate(evidence.source_authority) != capture.source_authority:
            raise TwinIdentityError("persisted rename evidence has a different source authority")
        expected_evidence_type = {
            ContinuityProofKind.AUTHORITATIVE_RENAME: "snowflake.rename",
            ContinuityProofKind.DECLARED_DBT_IDENTITY: "dbt.manifest",
        }[continuity.proof_kind]
        if evidence.evidence_type != expected_evidence_type:
            raise TwinIdentityError(
                f"{continuity.proof_kind.value} requires {expected_evidence_type} evidence"
            )
        if not await self._asset_rows(continuity.asset_id):
            raise TwinIdentityError("rename continuity refers to an unknown asset")

    async def _require_asset(self, asset_id: UUID, asset_version: int) -> TwinAssetModel:
        row = await self._session.get(TwinAssetModel, (asset_id, asset_version))
        if row is None:
            raise LookupError(f"Twin asset {asset_id}@{asset_version} is missing")
        return row

    async def _require_relationship(
        self, relationship_id: UUID, relationship_version: int
    ) -> TwinRelationshipModel:
        row = await self._session.get(
            TwinRelationshipModel, (relationship_id, relationship_version)
        )
        if row is None:
            raise LookupError(
                f"Twin relationship {relationship_id}@{relationship_version} is missing"
            )
        return row

    async def _require_observation(self, observation_id: UUID) -> TwinObservationModel:
        row = await self._session.get(TwinObservationModel, observation_id)
        if row is None:
            raise LookupError(f"Twin observation {observation_id} is missing")
        return row

    async def _require_evidence(self, evidence_ref_id: UUID) -> EvidenceReferenceModel:
        row = await self._session.get(EvidenceReferenceModel, evidence_ref_id)
        if row is None:
            raise LookupError(f"evidence reference {evidence_ref_id} is missing")
        return row


def _resolve_relationship(
    capture: PendingRelationshipCapture,
    assets_by_key: dict[str, TwinAsset],
) -> RelationshipCapture:
    from_asset_id = (
        assets_by_key[capture.from_capture_key].asset_id
        if capture.from_capture_key is not None
        else None
    )
    to_asset_id = (
        assets_by_key[capture.to_capture_key].asset_id
        if capture.to_capture_key is not None
        else None
    )
    return capture.resolved(from_asset_id=from_asset_id, to_asset_id=to_asset_id)


def _resolve_observation(
    capture: PendingObservationCapture,
    assets_by_key: dict[str, TwinAsset],
) -> TwinObservation:
    subject_asset_id = capture.subject_asset_id
    if capture.subject_capture_key is not None:
        subject_asset_id = assets_by_key[capture.subject_capture_key].asset_id
    if subject_asset_id is None:
        raise TwinIdentityError("observation subject is unresolved")
    return TwinObservation(
        observation_id=uuid4(),
        subject_asset_id=subject_asset_id,
        kind=capture.kind,
        source_authority=capture.source_authority,
        environment=TwinEnvironment.DEVELOPMENT,
        value=capture.value,
        observed_at=capture.observed_at,
        effective_at=capture.effective_at,
        fresh_until=capture.fresh_until,
        confidence=capture.confidence,
        evidence_ref_id=capture.evidence_ref_id,
    )


def _authority_digest(authority: SourceAuthorityRef) -> str:
    return hashlib.sha256(canonical_json_bytes(authority.model_dump(mode="json"))).hexdigest()


def _locator_digest(locator: tuple[str, ...]) -> str:
    return hashlib.sha256(canonical_json_bytes(list(locator))).hexdigest()


def _validate_snapshot_digest(snapshot: TwinSnapshot) -> None:
    payload = snapshot_manifest_payload(
        schema_version=snapshot.schema_version,
        environment=snapshot.environment,
        captured_at=snapshot.captured_at,
        capture_cutoff=snapshot.capture_cutoff,
        asset_versions=snapshot.asset_versions,
        relationship_versions=snapshot.relationship_versions,
        observation_ids=snapshot.observation_ids,
        evidence_reference_ids=snapshot.evidence_reference_ids,
        source_authorities=snapshot.source_authorities,
    )
    actual = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if actual != snapshot.manifest_sha256:
        raise TwinIdentityError("Twin snapshot manifest digest does not match membership")


def _asset_from_row(row: TwinAssetModel) -> TwinAsset:
    return TwinAsset(
        asset_id=row.asset_id,
        asset_version=row.asset_version,
        kind=TwinAssetKind(row.kind),
        source_authority=SourceAuthorityRef.model_validate(row.source_authority),
        environment=TwinEnvironment(row.environment),
        native_key=row.native_key,
        canonical_locator=tuple(row.canonical_locator),
        parent_asset_id=row.parent_asset_id,
        platform_type=row.platform_type,
        attributes=row.attributes,
        first_observed_at=row.first_observed_at,
        observed_at=row.observed_at,
        evidence_ref_id=row.evidence_ref_id,
    )


def _relationship_from_row(row: TwinRelationshipModel) -> TwinRelationship:
    return TwinRelationship(
        relationship_id=row.relationship_id,
        relationship_version=row.relationship_version,
        kind=TwinRelationshipKind(row.kind),
        from_asset_id=row.from_asset_id,
        to_asset_id=row.to_asset_id,
        source_authority=SourceAuthorityRef.model_validate(row.source_authority),
        environment=TwinEnvironment(row.environment),
        confidence=float(row.confidence),
        attributes=row.attributes,
        observed_at=row.observed_at,
        evidence_ref_id=row.evidence_ref_id,
    )


def _observation_from_row(row: TwinObservationModel) -> TwinObservation:
    return TwinObservation(
        observation_id=row.observation_id,
        subject_asset_id=row.subject_asset_id,
        kind=TwinObservationKind(row.kind),
        source_authority=SourceAuthorityRef.model_validate(row.source_authority),
        environment=TwinEnvironment(row.environment),
        value=row.value,
        observed_at=row.observed_at,
        effective_at=row.effective_at,
        fresh_until=row.fresh_until,
        confidence=float(row.confidence),
        evidence_ref_id=row.evidence_ref_id,
    )


def _evidence_from_row(row: EvidenceReferenceModel) -> EvidenceReference:
    return EvidenceReference(
        evidence_ref_id=row.evidence_ref_id,
        evidence_type=row.evidence_type,
        artifact_id=row.artifact_id,
        immutable_uri=row.immutable_uri,
        media_type=row.media_type,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        execution_mode=ExecutionMode(row.execution_mode),
        source_authority=SourceAuthorityRef.model_validate(row.source_authority),
        producer_operation_key=row.producer_operation_key,
        producer_attempt_id=row.producer_attempt_id,
        created_at=row.created_at,
    )


__all__ = ["PersistedCapture", "TwinRepository", "TwinSnapshotRecords"]
