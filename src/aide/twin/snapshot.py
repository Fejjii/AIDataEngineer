"""Deterministic construction of immutable Twin snapshot manifests."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime
from uuid import UUID, uuid4

from aide.domain.identity import canonical_json_bytes
from aide.domain.twin import (
    EvidenceReference,
    SourceAuthorityRef,
    TwinAsset,
    TwinEnvironment,
    TwinObservation,
    TwinRelationship,
    TwinSnapshot,
)
from aide.twin.errors import TwinFailureCode, TwinValidationError


def build_twin_snapshot(
    *,
    assets: Iterable[TwinAsset],
    relationships: Iterable[TwinRelationship],
    observations: Iterable[TwinObservation],
    evidence_references: Iterable[EvidenceReference],
    captured_at: datetime,
    capture_cutoff: datetime,
    twin_snapshot_id: UUID | None = None,
    schema_version: int = 1,
    required_observation_ids: frozenset[UUID] = frozenset(),
) -> TwinSnapshot:
    """Pin exact members and hash their canonical manifest independent of input order."""
    asset_items = tuple(assets)
    relationship_items = tuple(relationships)
    observation_items = tuple(observations)
    evidence_items = tuple(evidence_references)
    _validate_environment(asset_items, relationship_items, observation_items)
    _validate_cutoff(
        assets=asset_items,
        relationships=relationship_items,
        observations=observation_items,
        evidence_references=evidence_items,
        capture_cutoff=capture_cutoff,
    )
    _validate_reference_completeness(
        assets=asset_items,
        relationships=relationship_items,
        observations=observation_items,
        evidence_references=evidence_items,
    )
    _validate_required_freshness(
        observation_items,
        required_observation_ids=required_observation_ids,
        captured_at=captured_at,
    )
    asset_versions = _one_version_per_identity(
        ((item.asset_id, item.asset_version) for item in asset_items),
        member_name="asset",
    )
    relationship_versions = _one_version_per_identity(
        ((item.relationship_id, item.relationship_version) for item in relationship_items),
        member_name="relationship",
    )
    observation_ids = tuple(sorted({item.observation_id for item in observation_items}, key=str))
    evidence_ids = tuple(sorted({item.evidence_ref_id for item in evidence_items}, key=str))
    authorities = _source_authorities(
        assets=asset_items,
        relationships=relationship_items,
        observations=observation_items,
        evidence_references=evidence_items,
    )
    manifest = snapshot_manifest_payload(
        schema_version=schema_version,
        environment=TwinEnvironment.DEVELOPMENT,
        captured_at=captured_at,
        capture_cutoff=capture_cutoff,
        asset_versions=asset_versions,
        relationship_versions=relationship_versions,
        observation_ids=observation_ids,
        evidence_reference_ids=evidence_ids,
        source_authorities=authorities,
    )
    digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    return TwinSnapshot(
        twin_snapshot_id=twin_snapshot_id or uuid4(),
        schema_version=schema_version,
        environment=TwinEnvironment.DEVELOPMENT,
        captured_at=captured_at,
        capture_cutoff=capture_cutoff,
        asset_versions=asset_versions,
        relationship_versions=relationship_versions,
        observation_ids=observation_ids,
        evidence_reference_ids=evidence_ids,
        source_authorities=authorities,
        manifest_sha256=digest,
    )


def snapshot_manifest_payload(
    *,
    schema_version: int,
    environment: TwinEnvironment,
    captured_at: datetime,
    capture_cutoff: datetime,
    asset_versions: tuple[tuple[UUID, int], ...],
    relationship_versions: tuple[tuple[UUID, int], ...],
    observation_ids: tuple[UUID, ...],
    evidence_reference_ids: tuple[UUID, ...],
    source_authorities: tuple[SourceAuthorityRef, ...],
) -> dict[str, object]:
    """Return the exact canonical snapshot content covered by ``manifest_sha256``."""
    return {
        "schema_version": schema_version,
        "environment": environment.value,
        "captured_at": captured_at.isoformat(),
        "capture_cutoff": capture_cutoff.isoformat(),
        "asset_versions": [[str(member_id), version] for member_id, version in asset_versions],
        "relationship_versions": [
            [str(member_id), version] for member_id, version in relationship_versions
        ],
        "observation_ids": [str(item) for item in observation_ids],
        "evidence_reference_ids": [str(item) for item in evidence_reference_ids],
        "source_authorities": [item.model_dump(mode="json") for item in source_authorities],
    }


def _validate_environment(
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
) -> None:
    records = (*assets, *relationships, *observations)
    mismatched = [item for item in records if item.environment is not TwinEnvironment.DEVELOPMENT]
    if mismatched:
        raise TwinValidationError(
            TwinFailureCode.ENVIRONMENT_MISMATCH,
            "all MVP Twin members must be DEVELOPMENT",
        )


def _validate_cutoff(
    *,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    evidence_references: tuple[EvidenceReference, ...],
    capture_cutoff: datetime,
) -> None:
    observed = (
        *(item.observed_at for item in assets),
        *(item.observed_at for item in relationships),
        *(item.observed_at for item in observations),
        *(item.created_at for item in evidence_references),
    )
    if any(item > capture_cutoff for item in observed):
        raise TwinValidationError(
            TwinFailureCode.SNAPSHOT_MEMBER_MISMATCH,
            "snapshot contains a member newer than its capture cutoff",
        )


def _validate_reference_completeness(
    *,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    evidence_references: tuple[EvidenceReference, ...],
) -> None:
    evidence_ids = {item.evidence_ref_id for item in evidence_references}
    required = {
        *(item.evidence_ref_id for item in assets),
        *(item.evidence_ref_id for item in relationships),
        *(item.evidence_ref_id for item in observations),
    }
    missing = required - evidence_ids
    if missing:
        raise TwinValidationError(
            TwinFailureCode.SNAPSHOT_MEMBER_MISMATCH,
            f"snapshot omits referenced evidence IDs: {sorted(map(str, missing))}",
        )


def _validate_required_freshness(
    observations: tuple[TwinObservation, ...],
    *,
    required_observation_ids: frozenset[UUID],
    captured_at: datetime,
) -> None:
    by_id = {item.observation_id: item for item in observations}
    missing = required_observation_ids - by_id.keys()
    if missing:
        raise TwinValidationError(
            TwinFailureCode.FRESHNESS_REQUIRED,
            f"required observations are missing: {sorted(map(str, missing))}",
        )
    stale = [
        item.observation_id
        for item in observations
        if item.observation_id in required_observation_ids
        and (item.fresh_until is None or item.fresh_until < captured_at)
    ]
    if stale:
        raise TwinValidationError(
            TwinFailureCode.FRESHNESS_REQUIRED,
            f"required observations are stale: {sorted(map(str, stale))}",
        )


def _one_version_per_identity(
    members: Iterable[tuple[UUID, int]],
    *,
    member_name: str,
) -> tuple[tuple[UUID, int], ...]:
    result = tuple(sorted(set(members), key=lambda item: (str(item[0]), item[1])))
    identities = [item[0] for item in result]
    if len(identities) != len(set(identities)):
        raise TwinValidationError(
            TwinFailureCode.SNAPSHOT_MEMBER_MISMATCH,
            f"snapshot pins multiple versions of one {member_name}",
        )
    return result


def _source_authorities(
    *,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    evidence_references: tuple[EvidenceReference, ...],
) -> tuple[SourceAuthorityRef, ...]:
    authorities = {
        *(item.source_authority for item in assets),
        *(item.source_authority for item in relationships),
        *(item.source_authority for item in observations),
        *(item.source_authority for item in evidence_references),
    }
    return tuple(sorted(authorities, key=SourceAuthorityRef.sort_key))


__all__ = ["build_twin_snapshot", "snapshot_manifest_payload"]
