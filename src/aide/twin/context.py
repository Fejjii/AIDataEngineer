"""Deterministic, bounded, and permission-aware EstateContext assembly."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from aide.domain.artifacts import ExecutionMode
from aide.domain.identity import canonical_json_bytes
from aide.domain.permissions import PermissionLevel
from aide.domain.twin import (
    EstateContext,
    EvidenceReference,
    SourceAuthorityRef,
    TwinAsset,
    TwinAssetKind,
    TwinEnvironment,
    TwinModel,
    TwinObservation,
    TwinObservationKind,
    TwinRelationship,
    TwinRelationshipKind,
    TwinSnapshot,
)
from aide.twin.errors import TwinFailureCode, TwinValidationError

EXPANDABLE_RELATIONSHIPS = frozenset(
    {
        TwinRelationshipKind.CONTAINS,
        TwinRelationshipKind.TRANSFORMS_FROM,
        TwinRelationshipKind.TESTS,
    }
)
_FORBIDDEN_VALUE_KEYS = frozenset(
    {"raw_rows", "rows", "sample_rows", "samples", "source_rows", "unmasked_samples"}
)


class EstateContextLimits(TwinModel):
    max_top_level_assets: int = Field(default=12, ge=1)
    max_fields: int = Field(default=120, ge=1)
    max_relationships: int = Field(default=64, ge=1)
    max_observations: int = Field(default=32, ge=1)
    max_relationship_depth: int = Field(default=2, ge=0, le=2)
    max_serialized_bytes: int = Field(default=64 * 1024, ge=1)


class EstateAccessPolicy(TwinModel):
    """Server-derived grant and connector-scope intersection."""

    effective_grants: frozenset[PermissionLevel]
    allowed_asset_ids: frozenset[UUID]
    allowed_authority_ids: frozenset[str] = frozenset()


class EstateContextRequest(TwinModel):
    request_terms: tuple[str, ...] = ()
    mandatory_asset_ids: frozenset[UUID] = frozenset()
    reasoner_asset_ids: tuple[UUID, ...] | None = None
    required_observation_ids: frozenset[UUID] = frozenset()
    required_observation_kinds: frozenset[TwinObservationKind] = frozenset()
    required_execution_mode: ExecutionMode | None = None


@dataclass(frozen=True)
class CanonicalEstateContext:
    context: EstateContext
    serialized: bytes


def assemble_estate_context(
    *,
    snapshot: TwinSnapshot,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    evidence_references: tuple[EvidenceReference, ...],
    access: EstateAccessPolicy,
    request: EstateContextRequest,
    limits: EstateContextLimits | None = None,
) -> CanonicalEstateContext:
    """Assemble one byte-stable context or fail closed without truncation."""
    active_limits = limits or EstateContextLimits()
    _validate_snapshot_members(
        snapshot=snapshot,
        assets=assets,
        relationships=relationships,
        observations=observations,
        evidence_references=evidence_references,
    )
    eligible = _eligible_assets(assets, access)
    candidate_ids = _candidate_asset_ids(tuple(eligible.values()), request.request_terms)
    _require_subset(
        request.mandatory_asset_ids,
        eligible.keys(),
        detail="mandatory asset is outside trusted grants or connector scope",
    )
    if request.reasoner_asset_ids is not None:
        proposed = frozenset(request.reasoner_asset_ids)
        _require_subset(
            proposed,
            candidate_ids,
            detail="reasoner proposed an ID outside the eligible candidate set",
        )
        selected_ids = set(proposed)
    else:
        selected_ids = set(candidate_ids)
    selected_ids.update(request.mandatory_asset_ids)
    expanded_ids, expanded_relationships = _expand_relationships(
        selected_ids=selected_ids,
        eligible_ids=frozenset(eligible),
        relationships=relationships,
        max_depth=active_limits.max_relationship_depth,
    )
    selected_assets = tuple(sorted((eligible[item] for item in expanded_ids), key=_asset_key))
    selected_relationships = tuple(sorted(expanded_relationships, key=_relationship_key))
    selected_observations = tuple(
        sorted(
            (item for item in observations if item.subject_asset_id in expanded_ids),
            key=lambda item: str(item.observation_id),
        )
    )
    _validate_required_observations(
        selected_observations,
        request=request,
        captured_at=snapshot.captured_at,
    )
    _validate_authority_conflicts(selected_observations, request)
    for observation in selected_observations:
        unsafe_path = _unsafe_value_path(observation.value)
        if unsafe_path is not None:
            raise TwinValidationError(
                TwinFailureCode.UNSAFE_CONTEXT_VALUE,
                f"observation {observation.observation_id} contains {unsafe_path}",
            )
    evidence_ids = {
        *(item.evidence_ref_id for item in selected_assets),
        *(item.evidence_ref_id for item in selected_relationships),
        *(item.evidence_ref_id for item in selected_observations),
    }
    selected_evidence = tuple(
        sorted(
            (item for item in evidence_references if item.evidence_ref_id in evidence_ids),
            key=lambda item: str(item.evidence_ref_id),
        )
    )
    _validate_execution_modes(selected_evidence, request.required_execution_mode)
    authorities = _context_authorities(
        assets=selected_assets,
        relationships=selected_relationships,
        observations=selected_observations,
        evidence_references=selected_evidence,
    )
    _validate_count_bounds(
        assets=selected_assets,
        relationships=selected_relationships,
        observations=selected_observations,
        limits=active_limits,
    )
    context_payload: dict[str, Any] = {
        "schema_version": 1,
        "twin_snapshot_id": str(snapshot.twin_snapshot_id),
        "environment": snapshot.environment.value,
        "assets": [item.model_dump(mode="json") for item in selected_assets],
        "relationships": [item.model_dump(mode="json") for item in selected_relationships],
        "observations": [item.model_dump(mode="json") for item in selected_observations],
        "evidence_references": [item.model_dump(mode="json") for item in selected_evidence],
        "source_authorities": [item.model_dump(mode="json") for item in authorities],
    }
    digest = hashlib.sha256(canonical_json_bytes(context_payload)).hexdigest()
    context = EstateContext(
        **context_payload,
        estate_context_sha256=digest,
    )
    serialized = canonical_json_bytes(context.model_dump(mode="json"))
    if len(serialized) > active_limits.max_serialized_bytes:
        raise TwinValidationError(
            TwinFailureCode.CONTEXT_BOUND_EXCEEDED,
            f"canonical context uses {len(serialized)} bytes; "
            f"limit is {active_limits.max_serialized_bytes}",
        )
    return CanonicalEstateContext(context=context, serialized=serialized)


def _validate_snapshot_members(
    *,
    snapshot: TwinSnapshot,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    evidence_references: tuple[EvidenceReference, ...],
) -> None:
    actual_assets = tuple(
        sorted(
            {(item.asset_id, item.asset_version) for item in assets},
            key=lambda item: (str(item[0]), item[1]),
        )
    )
    actual_relationships = tuple(
        sorted(
            {(item.relationship_id, item.relationship_version) for item in relationships},
            key=lambda item: (str(item[0]), item[1]),
        )
    )
    actual_observations = tuple(sorted({item.observation_id for item in observations}, key=str))
    actual_evidence = tuple(sorted({item.evidence_ref_id for item in evidence_references}, key=str))
    if (
        actual_assets != snapshot.asset_versions
        or actual_relationships != snapshot.relationship_versions
        or actual_observations != snapshot.observation_ids
        or actual_evidence != snapshot.evidence_reference_ids
    ):
        raise TwinValidationError(
            TwinFailureCode.SNAPSHOT_MEMBER_MISMATCH,
            "loaded context records do not exactly match pinned snapshot membership",
        )
    if (
        any(item.environment != snapshot.environment for item in assets)
        or any(item.environment != snapshot.environment for item in relationships)
        or any(item.environment != snapshot.environment for item in observations)
    ):
        raise TwinValidationError(
            TwinFailureCode.ENVIRONMENT_MISMATCH,
            "context record environment differs from the pinned snapshot",
        )


def _eligible_assets(
    assets: tuple[TwinAsset, ...], access: EstateAccessPolicy
) -> dict[UUID, TwinAsset]:
    if PermissionLevel.READ not in access.effective_grants:
        return {}
    return {
        item.asset_id: item
        for item in assets
        if item.environment is TwinEnvironment.DEVELOPMENT
        and item.asset_id in access.allowed_asset_ids
        and (
            not access.allowed_authority_ids
            or item.source_authority.authority_id in access.allowed_authority_ids
        )
    }


def _candidate_asset_ids(
    assets: tuple[TwinAsset, ...], request_terms: tuple[str, ...]
) -> frozenset[UUID]:
    terms = tuple(sorted({term.casefold().strip() for term in request_terms if term.strip()}))
    if not terms:
        return frozenset(item.asset_id for item in assets)
    candidates: set[UUID] = set()
    for asset in assets:
        searchable = " ".join(
            (
                *asset.canonical_locator,
                asset.platform_type,
                str(asset.attributes.get("name", "")),
                str(asset.attributes.get("description", "")),
            )
        ).casefold()
        if any(term in searchable for term in terms):
            candidates.add(asset.asset_id)
    return frozenset(candidates)


def _require_subset(
    proposed: frozenset[UUID],
    eligible: Iterable[UUID],
    *,
    detail: str,
) -> None:
    eligible_ids = frozenset(eligible)
    outside = proposed - eligible_ids
    if outside:
        raise TwinValidationError(
            TwinFailureCode.OUT_OF_SCOPE_ASSET,
            f"{detail}: {sorted(map(str, outside))}",
        )


def _expand_relationships(
    *,
    selected_ids: set[UUID],
    eligible_ids: frozenset[UUID],
    relationships: tuple[TwinRelationship, ...],
    max_depth: int,
) -> tuple[frozenset[UUID], tuple[TwinRelationship, ...]]:
    adjacency: dict[UUID, list[tuple[UUID, TwinRelationship]]] = {}
    for relationship in relationships:
        if relationship.kind not in EXPANDABLE_RELATIONSHIPS:
            continue
        if (
            relationship.from_asset_id not in eligible_ids
            or relationship.to_asset_id not in eligible_ids
        ):
            continue
        adjacency.setdefault(relationship.from_asset_id, []).append(
            (relationship.to_asset_id, relationship)
        )
        adjacency.setdefault(relationship.to_asset_id, []).append(
            (relationship.from_asset_id, relationship)
        )
    queue = deque((asset_id, 0) for asset_id in sorted(selected_ids, key=str))
    expanded = set(selected_ids)
    included_relationships: dict[tuple[UUID, int], TwinRelationship] = {}
    while queue:
        asset_id, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor_id, relationship in sorted(
            adjacency.get(asset_id, ()),
            key=lambda item: (_relationship_key(item[1]), str(item[0])),
        ):
            included_relationships[
                (relationship.relationship_id, relationship.relationship_version)
            ] = relationship
            if neighbor_id in expanded:
                continue
            expanded.add(neighbor_id)
            queue.append((neighbor_id, depth + 1))
    return frozenset(expanded), tuple(included_relationships.values())


def _validate_required_observations(
    observations: tuple[TwinObservation, ...],
    *,
    request: EstateContextRequest,
    captured_at: datetime,
) -> None:
    by_id = {item.observation_id: item for item in observations}
    missing_ids = request.required_observation_ids - by_id.keys()
    if missing_ids:
        raise TwinValidationError(
            TwinFailureCode.FRESHNESS_REQUIRED,
            f"required observations are absent from selected context: "
            f"{sorted(map(str, missing_ids))}",
        )
    required = [
        item
        for item in observations
        if item.observation_id in request.required_observation_ids
        or item.kind in request.required_observation_kinds
    ]
    present_kinds = {item.kind for item in required}
    missing_kinds = request.required_observation_kinds - present_kinds
    if missing_kinds:
        raise TwinValidationError(
            TwinFailureCode.FRESHNESS_REQUIRED,
            f"required observation kinds are absent: "
            f"{sorted(item.value for item in missing_kinds)}",
        )
    stale = [
        item.observation_id
        for item in required
        if item.fresh_until is None or item.fresh_until < captured_at
    ]
    if stale:
        raise TwinValidationError(
            TwinFailureCode.FRESHNESS_REQUIRED,
            f"required observations are stale: {sorted(map(str, stale))}",
        )


def _validate_authority_conflicts(
    observations: tuple[TwinObservation, ...], request: EstateContextRequest
) -> None:
    required = [
        item
        for item in observations
        if item.observation_id in request.required_observation_ids
        or item.kind in request.required_observation_kinds
    ]
    groups: dict[tuple[UUID, TwinObservationKind], list[TwinObservation]] = {}
    for item in required:
        if item.confidence == 1:
            groups.setdefault((item.subject_asset_id, item.kind), []).append(item)
    for (asset_id, kind), items in groups.items():
        values = {canonical_json_bytes(item.value) for item in items}
        authorities = {item.source_authority for item in items}
        if len(values) > 1 and len(authorities) > 1:
            raise TwinValidationError(
                TwinFailureCode.AUTHORITY_CONFLICT,
                f"unresolved authoritative {kind.value} conflict for asset {asset_id}",
            )


def _validate_execution_modes(
    evidence_references: tuple[EvidenceReference, ...],
    required_mode: ExecutionMode | None,
) -> None:
    modes = {ExecutionMode(item.execution_mode) for item in evidence_references}
    if len(modes) > 1:
        raise TwinValidationError(
            TwinFailureCode.EVIDENCE_CONTAMINATION,
            "REAL and MOCK evidence cannot coexist in one EstateContext",
        )
    if required_mode is not None and modes and modes != {required_mode}:
        raise TwinValidationError(
            TwinFailureCode.EVIDENCE_CONTAMINATION,
            f"context requires {required_mode.value} evidence",
        )


def _validate_count_bounds(
    *,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    limits: EstateContextLimits,
) -> None:
    top_level = sum(
        item.kind in {TwinAssetKind.DATASET, TwinAssetKind.TRANSFORMATION}
        and item.parent_asset_id is None
        for item in assets
    )
    fields = sum(item.kind is TwinAssetKind.FIELD for item in assets)
    checks = (
        ("top-level assets", top_level, limits.max_top_level_assets),
        ("fields", fields, limits.max_fields),
        ("relationships", len(relationships), limits.max_relationships),
        ("observations", len(observations), limits.max_observations),
    )
    for label, actual, maximum in checks:
        if actual > maximum:
            raise TwinValidationError(
                TwinFailureCode.CONTEXT_BOUND_EXCEEDED,
                f"{label} count {actual} exceeds limit {maximum}",
            )


def _unsafe_value_path(value: object, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in _FORBIDDEN_VALUE_KEYS:
                return f"{path}.{key}"
            found = _unsafe_value_path(item, f"{path}.{key}")
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _unsafe_value_path(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _context_authorities(
    *,
    assets: tuple[TwinAsset, ...],
    relationships: tuple[TwinRelationship, ...],
    observations: tuple[TwinObservation, ...],
    evidence_references: tuple[EvidenceReference, ...],
) -> tuple[SourceAuthorityRef, ...]:
    values = {
        *(item.source_authority for item in assets),
        *(item.source_authority for item in relationships),
        *(item.source_authority for item in observations),
        *(item.source_authority for item in evidence_references),
    }
    return tuple(sorted(values, key=SourceAuthorityRef.sort_key))


def _asset_key(item: TwinAsset) -> tuple[str, int]:
    return str(item.asset_id), item.asset_version


def _relationship_key(item: TwinRelationship) -> tuple[str, int]:
    return str(item.relationship_id), item.relationship_version


__all__ = [
    "CanonicalEstateContext",
    "EstateAccessPolicy",
    "EstateContextLimits",
    "EstateContextRequest",
    "assemble_estate_context",
]
