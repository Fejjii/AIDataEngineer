from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from aide.domain.artifacts import ExecutionMode
from aide.domain.permissions import PermissionLevel
from aide.domain.twin import (
    EvidenceReference,
    SourceAuthorityRef,
    TwinAsset,
    TwinAssetKind,
    TwinObservation,
    TwinObservationKind,
    TwinRelationship,
    TwinRelationshipKind,
)
from aide.twin.context import (
    EstateAccessPolicy,
    EstateContextLimits,
    EstateContextRequest,
    assemble_estate_context,
)
from aide.twin.errors import TwinFailureCode, TwinValidationError
from aide.twin.identity import AssetCapture, materialize_asset_version
from aide.twin.snapshot import build_twin_snapshot

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
SNOWFLAKE = SourceAuthorityRef(
    authority_id="snowflake_ro",
    contract_version="1.0",
    scope=("VANTARA_RAW",),
)
DBT = SourceAuthorityRef(
    authority_id="dbt_core",
    contract_version="1.0",
    scope=("vantara",),
)


def _evidence(
    *,
    authority: SourceAuthorityRef = SNOWFLAKE,
    mode: ExecutionMode = ExecutionMode.REAL,
) -> EvidenceReference:
    return EvidenceReference(
        evidence_ref_id=uuid4(),
        evidence_type="metadata",
        media_type="application/json",
        sha256="a" * 64,
        size_bytes=1,
        execution_mode=mode.value,
        source_authority=authority,
        created_at=NOW,
    )


def _capture(
    evidence: EvidenceReference,
    *,
    locator: tuple[str, ...] = ("VANTARA_RAW", "BILLING", "INVOICES"),
    native_key: str | None = "snowflake-object-1",
    attributes: dict[str, object] | None = None,
) -> AssetCapture:
    return AssetCapture(
        kind=TwinAssetKind.DATASET,
        source_authority=evidence.source_authority,
        native_key=native_key,
        canonical_locator=locator,
        platform_type="snowflake.table",
        attributes=attributes or {"columns": 5},
        observed_at=NOW,
        evidence_ref_id=evidence.evidence_ref_id,
    )


def _asset(
    evidence: EvidenceReference,
    *,
    asset_id: UUID | None = None,
    name: str = "INVOICES",
) -> TwinAsset:
    return materialize_asset_version(
        _capture(
            evidence,
            locator=("VANTARA_RAW", "BILLING", name),
            native_key=f"snowflake-{name}",
        ),
        identity_asset_id=asset_id,
    )


def _snapshot(
    *,
    assets: tuple[TwinAsset, ...],
    evidence: tuple[EvidenceReference, ...],
    observations: tuple[TwinObservation, ...] = (),
) -> object:
    return build_twin_snapshot(
        assets=assets,
        relationships=(),
        observations=observations,
        evidence_references=evidence,
        captured_at=NOW + timedelta(minutes=1),
        capture_cutoff=NOW + timedelta(minutes=1),
    )


def _access(*assets: TwinAsset) -> EstateAccessPolicy:
    return EstateAccessPolicy(
        effective_grants=frozenset({PermissionLevel.READ}),
        allowed_asset_ids=frozenset(item.asset_id for item in assets),
    )


def test_at01_stable_identity_versions_and_history_are_immutable() -> None:
    evidence = _evidence()
    first = materialize_asset_version(_capture(evidence))
    repeated = materialize_asset_version(_capture(evidence), existing_versions=(first,))
    changed = materialize_asset_version(
        _capture(evidence, attributes={"columns": 6}),
        existing_versions=(first,),
    )

    assert repeated is first
    assert changed.asset_id == first.asset_id
    assert changed.asset_version == 2
    assert first.asset_version == 1
    assert first.attributes == {"columns": 5}
    with pytest.raises(ValidationError):
        first.attributes = {"columns": 99}  # type: ignore[misc]


def test_at02_rename_continuity_requires_authoritative_identity_resolution() -> None:
    evidence = _evidence()
    original = materialize_asset_version(
        _capture(evidence, native_key=None),
    )
    renamed_capture = _capture(
        evidence,
        locator=("VANTARA_RAW", "BILLING", "BILLING_INVOICES"),
        native_key=None,
    )
    unproven = materialize_asset_version(renamed_capture)
    proven = materialize_asset_version(
        renamed_capture,
        existing_versions=(original,),
        identity_asset_id=original.asset_id,
    )
    recreated = materialize_asset_version(_capture(evidence, native_key=None))

    assert unproven.asset_id != original.asset_id
    assert recreated.asset_id != original.asset_id
    assert proven.asset_id == original.asset_id
    assert proven.asset_version == 2


def test_at03_snapshot_digest_is_order_independent_and_member_sensitive() -> None:
    first_evidence = _evidence()
    second_evidence = _evidence(authority=DBT)
    first = _asset(first_evidence, name="INVOICES")
    second = _asset(second_evidence, name="CUSTOMER_REVENUE")
    kwargs = {
        "relationships": (),
        "observations": (),
        "captured_at": NOW + timedelta(minutes=1),
        "capture_cutoff": NOW + timedelta(minutes=1),
    }
    forward = build_twin_snapshot(
        assets=(first, second),
        evidence_references=(first_evidence, second_evidence),
        **kwargs,
    )
    reverse = build_twin_snapshot(
        assets=(second, first),
        evidence_references=(second_evidence, first_evidence),
        **kwargs,
    )
    changed = build_twin_snapshot(
        assets=(
            first.model_copy(update={"asset_version": 2}),
            second,
        ),
        evidence_references=(first_evidence, second_evidence),
        **kwargs,
    )

    assert forward.manifest_sha256 == reverse.manifest_sha256
    assert forward.manifest_sha256 != changed.manifest_sha256


def test_at04_authority_conflict_blocks_required_context() -> None:
    snowflake_evidence = _evidence()
    dbt_evidence = _evidence(authority=DBT)
    asset = _asset(snowflake_evidence)
    observations = (
        _observation(asset, snowflake_evidence, {"columns": ["INVOICE_STATUS"]}),
        _observation(asset, dbt_evidence, {"columns": ["STATUS"]}),
    )
    snapshot = build_twin_snapshot(
        assets=(asset,),
        relationships=(),
        observations=observations,
        evidence_references=(snowflake_evidence, dbt_evidence),
        captured_at=NOW + timedelta(minutes=1),
        capture_cutoff=NOW + timedelta(minutes=1),
    )

    with pytest.raises(TwinValidationError) as raised:
        assemble_estate_context(
            snapshot=snapshot,
            assets=(asset,),
            relationships=(),
            observations=observations,
            evidence_references=(snowflake_evidence, dbt_evidence),
            access=_access(asset),
            request=EstateContextRequest(
                required_observation_kinds=frozenset({TwinObservationKind.SCHEMA})
            ),
        )

    assert raised.value.code is TwinFailureCode.AUTHORITY_CONFLICT


def test_at04_stale_required_observation_blocks_snapshot_and_context() -> None:
    evidence = _evidence()
    asset = _asset(evidence)
    stale = _observation(
        asset,
        evidence,
        {"columns": ["INVOICE_STATUS"]},
        fresh_until=NOW + timedelta(seconds=30),
    )

    with pytest.raises(TwinValidationError) as pin_error:
        build_twin_snapshot(
            assets=(asset,),
            relationships=(),
            observations=(stale,),
            evidence_references=(evidence,),
            captured_at=NOW + timedelta(minutes=1),
            capture_cutoff=NOW + timedelta(minutes=1),
            required_observation_ids=frozenset({stale.observation_id}),
        )
    assert pin_error.value.code is TwinFailureCode.FRESHNESS_REQUIRED

    snapshot = _snapshot(assets=(asset,), evidence=(evidence,), observations=(stale,))
    with pytest.raises(TwinValidationError) as context_error:
        assemble_estate_context(
            snapshot=snapshot,  # type: ignore[arg-type]
            assets=(asset,),
            relationships=(),
            observations=(stale,),
            evidence_references=(evidence,),
            access=_access(asset),
            request=EstateContextRequest(
                required_observation_ids=frozenset({stale.observation_id})
            ),
        )
    assert context_error.value.code is TwinFailureCode.FRESHNESS_REQUIRED


def test_at04_real_mock_contamination_and_non_development_are_rejected() -> None:
    real_evidence = _evidence()
    mock_evidence = _evidence(mode=ExecutionMode.MOCK)
    first = _asset(real_evidence, name="INVOICES")
    second = _asset(mock_evidence, name="PAYMENTS")
    snapshot = _snapshot(assets=(first, second), evidence=(real_evidence, mock_evidence))

    with pytest.raises(TwinValidationError) as raised:
        assemble_estate_context(
            snapshot=snapshot,  # type: ignore[arg-type]
            assets=(first, second),
            relationships=(),
            observations=(),
            evidence_references=(real_evidence, mock_evidence),
            access=_access(first, second),
            request=EstateContextRequest(),
        )
    assert raised.value.code is TwinFailureCode.EVIDENCE_CONTAMINATION

    with pytest.raises(ValidationError):
        first.model_copy(update={"environment": "STAGING"}).model_validate(
            {**first.model_dump(), "environment": "STAGING"}
        )


def test_at05_pinned_snapshot_rejects_later_asset_versions() -> None:
    evidence = _evidence()
    first = _asset(evidence)
    snapshot = _snapshot(assets=(first,), evidence=(evidence,))
    later = materialize_asset_version(
        _capture(evidence, attributes={"columns": 7}),
        existing_versions=(first,),
    )

    with pytest.raises(TwinValidationError) as raised:
        assemble_estate_context(
            snapshot=snapshot,  # type: ignore[arg-type]
            assets=(later,),
            relationships=(),
            observations=(),
            evidence_references=(evidence,),
            access=_access(later),
            request=EstateContextRequest(),
        )
    assert raised.value.code is TwinFailureCode.SNAPSHOT_MEMBER_MISMATCH


def test_at06_permission_reasoner_and_bound_fail_closed() -> None:
    evidence = _evidence()
    allowed = _asset(evidence, name="INVOICES")
    denied = _asset(evidence, name="PAYMENTS")
    snapshot = _snapshot(assets=(allowed, denied), evidence=(evidence,))

    with pytest.raises(TwinValidationError) as reasoner_error:
        assemble_estate_context(
            snapshot=snapshot,  # type: ignore[arg-type]
            assets=(allowed, denied),
            relationships=(),
            observations=(),
            evidence_references=(evidence,),
            access=_access(allowed),
            request=EstateContextRequest(reasoner_asset_ids=(denied.asset_id,)),
        )
    assert reasoner_error.value.code is TwinFailureCode.OUT_OF_SCOPE_ASSET

    many_assets = tuple(_asset(evidence, name=f"TABLE_{index}") for index in range(13))
    overflow_snapshot = _snapshot(assets=many_assets, evidence=(evidence,))
    with pytest.raises(TwinValidationError) as bound_error:
        assemble_estate_context(
            snapshot=overflow_snapshot,  # type: ignore[arg-type]
            assets=many_assets,
            relationships=(),
            observations=(),
            evidence_references=(evidence,),
            access=_access(*many_assets),
            request=EstateContextRequest(
                mandatory_asset_ids=frozenset(item.asset_id for item in many_assets)
            ),
            limits=EstateContextLimits(max_top_level_assets=12),
        )
    assert bound_error.value.code is TwinFailureCode.CONTEXT_BOUND_EXCEEDED


def test_at07_repeated_context_assembly_is_byte_identical() -> None:
    evidence = _evidence()
    assets = (
        _asset(evidence, name="INVOICES"),
        _asset(evidence, name="PAYMENTS"),
    )
    snapshot = _snapshot(assets=assets, evidence=(evidence,))
    kwargs = {
        "snapshot": snapshot,
        "assets": tuple(reversed(assets)),
        "relationships": (),
        "observations": (),
        "evidence_references": (evidence,),
        "access": _access(*assets),
        "request": EstateContextRequest(),
    }

    first = assemble_estate_context(**kwargs)  # type: ignore[arg-type]
    second = assemble_estate_context(**kwargs)  # type: ignore[arg-type]

    assert first.serialized == second.serialized
    assert first.context.estate_context_sha256 == second.context.estate_context_sha256


def test_context_expansion_stops_at_depth_two_and_enforces_relationship_bound() -> None:
    evidence = _evidence()
    assets = tuple(_asset(evidence, name=f"TABLE_{index}") for index in range(4))
    relationships = tuple(
        _relationship(evidence, assets[index], assets[index + 1]) for index in range(3)
    )
    snapshot = build_twin_snapshot(
        assets=assets,
        relationships=relationships,
        observations=(),
        evidence_references=(evidence,),
        captured_at=NOW + timedelta(minutes=1),
        capture_cutoff=NOW + timedelta(minutes=1),
    )
    kwargs = {
        "snapshot": snapshot,
        "assets": assets,
        "relationships": relationships,
        "observations": (),
        "evidence_references": (evidence,),
        "access": _access(*assets),
        "request": EstateContextRequest(reasoner_asset_ids=(assets[0].asset_id,)),
    }

    assembled = assemble_estate_context(**kwargs)  # type: ignore[arg-type]
    assert tuple(item.asset_id for item in assembled.context.assets) == tuple(
        sorted((item.asset_id for item in assets[:3]), key=str)
    )
    assert len(assembled.context.relationships) == 2

    with pytest.raises(TwinValidationError) as raised:
        assemble_estate_context(
            **kwargs,  # type: ignore[arg-type]
            limits=EstateContextLimits(max_relationships=1),
        )
    assert raised.value.code is TwinFailureCode.CONTEXT_BOUND_EXCEEDED


def _observation(
    asset: TwinAsset,
    evidence: EvidenceReference,
    value: dict[str, object],
    *,
    fresh_until: datetime | None = None,
) -> TwinObservation:
    return TwinObservation(
        observation_id=uuid4(),
        subject_asset_id=asset.asset_id,
        kind=TwinObservationKind.SCHEMA,
        source_authority=evidence.source_authority,
        value=value,
        observed_at=NOW,
        fresh_until=fresh_until or NOW + timedelta(minutes=2),
        confidence=1,
        evidence_ref_id=evidence.evidence_ref_id,
    )


def _relationship(
    evidence: EvidenceReference,
    from_asset: TwinAsset,
    to_asset: TwinAsset,
) -> TwinRelationship:
    return TwinRelationship(
        relationship_id=uuid4(),
        relationship_version=1,
        kind=TwinRelationshipKind.TRANSFORMS_FROM,
        from_asset_id=from_asset.asset_id,
        to_asset_id=to_asset.asset_id,
        source_authority=evidence.source_authority,
        confidence=1,
        attributes={"declared": True},
        observed_at=NOW,
        evidence_ref_id=evidence.evidence_ref_id,
    )
