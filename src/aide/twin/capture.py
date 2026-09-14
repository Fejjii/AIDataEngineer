"""Pure capture adapters over existing Snowflake, dbt, and DE006 outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from aide.capabilities.io import DescribeAssetOutput, DiscoverAssetsOutput
from aide.connectors.dbt.artifacts import (
    node_results_from_run_results,
    test_results_from_run_results,
)
from aide.domain.twin import (
    SourceAuthorityRef,
    TwinAssetKind,
    TwinObservationKind,
    TwinRelationshipKind,
)
from aide.profiling.artifacts import ProfilingRunResult
from aide.twin.records import (
    PendingAssetCapture,
    PendingObservationCapture,
    PendingRelationshipCapture,
    TwinCaptureBatch,
)


def capture_snowflake_metadata(
    *,
    discovered: DiscoverAssetsOutput,
    descriptions: tuple[DescribeAssetOutput, ...],
    source_authority: SourceAuthorityRef,
    evidence_ref_id: UUID,
    observed_at: datetime,
    fresh_until: datetime,
    incarnations: dict[tuple[str, ...], int] | None = None,
) -> TwinCaptureBatch:
    """Convert selected Snowflake catalogue facts; never include business rows."""
    if discovered.truncated:
        raise ValueError("truncated Snowflake discovery cannot publish authoritative capture")
    description_by_locator = {item.asset.address: item for item in descriptions}
    discovered_by_locator = {item.address: item for item in discovered.assets}
    if set(description_by_locator) != set(discovered_by_locator):
        raise ValueError("every selected Snowflake asset requires one exact description")
    incarnation_by_locator = incarnations or {}
    assets: list[PendingAssetCapture] = []
    relationships: list[PendingRelationshipCapture] = []
    observations: list[PendingObservationCapture] = []
    for locator in sorted(discovered_by_locator):
        catalogued = discovered_by_locator[locator]
        described = description_by_locator[locator]
        dataset_key = _snowflake_dataset_key(locator)
        assets.append(
            PendingAssetCapture(
                capture_key=dataset_key,
                kind=TwinAssetKind.DATASET,
                source_authority=source_authority,
                canonical_locator=locator,
                incarnation=incarnation_by_locator.get(locator, 1),
                platform_type="snowflake.table",
                attributes={
                    "catalog_kind": catalogued.kind.value,
                    "row_count_estimate": catalogued.row_count_estimate,
                    "last_altered": (
                        catalogued.last_altered.isoformat()
                        if catalogued.last_altered is not None
                        else None
                    ),
                    "comment": catalogued.comment,
                    "primary_key": list(described.primary_key or ()),
                    "unique_keys": [list(item) for item in described.unique_keys],
                    "foreign_keys": [
                        {
                            "columns": list(item.columns),
                            "ref_locator": list(item.ref_asset.address),
                            "ref_columns": list(item.ref_columns),
                        }
                        for item in described.foreign_keys
                    ],
                    "row_count": described.row_count,
                },
                observed_at=observed_at,
                evidence_ref_id=evidence_ref_id,
            )
        )
        schema_columns: list[dict[str, Any]] = []
        for column in sorted(described.columns, key=lambda item: item.ordinal):
            field_key = _snowflake_field_key(locator, column.name)
            field_locator = (*locator, column.name)
            assets.append(
                PendingAssetCapture(
                    capture_key=field_key,
                    kind=TwinAssetKind.FIELD,
                    source_authority=source_authority,
                    canonical_locator=field_locator,
                    incarnation=incarnation_by_locator.get(field_locator, 1),
                    parent_capture_key=dataset_key,
                    platform_type="snowflake.column",
                    attributes={
                        "data_type": column.data_type,
                        "nullable": column.nullable,
                        "ordinal": column.ordinal,
                        "comment": column.comment,
                    },
                    observed_at=observed_at,
                    evidence_ref_id=evidence_ref_id,
                )
            )
            relationships.append(
                PendingRelationshipCapture(
                    capture_key=f"contains:{dataset_key}:{column.name}",
                    kind=TwinRelationshipKind.CONTAINS,
                    from_capture_key=dataset_key,
                    to_capture_key=field_key,
                    source_authority=source_authority,
                    confidence=1,
                    attributes={},
                    observed_at=observed_at,
                    evidence_ref_id=evidence_ref_id,
                )
            )
            schema_columns.append(
                {
                    "name": column.name,
                    "data_type": column.data_type,
                    "nullable": column.nullable,
                    "ordinal": column.ordinal,
                }
            )
        observations.append(
            PendingObservationCapture(
                subject_capture_key=dataset_key,
                kind=TwinObservationKind.SCHEMA,
                source_authority=source_authority,
                value={
                    "connector_snapshot_id": str(described.snapshot_id),
                    "columns": schema_columns,
                    "primary_key": list(described.primary_key or ()),
                },
                observed_at=observed_at,
                fresh_until=fresh_until,
                confidence=1,
                evidence_ref_id=evidence_ref_id,
            )
        )
    return TwinCaptureBatch(
        assets=tuple(assets),
        relationships=tuple(relationships),
        observations=tuple(observations),
    )


def capture_dbt_artifacts(
    *,
    manifest: dict[str, Any],
    run_results: dict[str, Any] | None,
    source_authority: SourceAuthorityRef,
    manifest_evidence_ref_id: UUID,
    run_results_evidence_ref_id: UUID | None,
    observed_at: datetime,
    fresh_until: datetime,
    external_asset_ids: dict[str, UUID] | None = None,
) -> TwinCaptureBatch:
    """Capture dbt models, tests, declared lineage, manifest identity, and run evidence."""
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        raise ValueError("manifest.json missing nodes object")
    external = external_asset_ids or {}
    manifest_identity = _manifest_identity(manifest)
    assets: list[PendingAssetCapture] = []
    relationships: list[PendingRelationshipCapture] = []
    observations: list[PendingObservationCapture] = []
    captured_ids: set[str] = set()
    for unique_id, raw_node in sorted(nodes.items()):
        if not isinstance(raw_node, dict):
            continue
        resource_type = str(raw_node.get("resource_type", ""))
        if resource_type not in {"model", "test"}:
            continue
        captured_ids.add(str(unique_id))
        assets.append(
            PendingAssetCapture(
                capture_key=_dbt_key(str(unique_id)),
                kind=(
                    TwinAssetKind.TRANSFORMATION if resource_type == "model" else TwinAssetKind.TEST
                ),
                source_authority=source_authority,
                native_key=str(unique_id),
                canonical_locator=_dbt_locator(raw_node, str(unique_id)),
                platform_type=f"dbt.{resource_type}",
                attributes=_dbt_node_attributes(raw_node, str(unique_id), manifest_identity),
                observed_at=observed_at,
                evidence_ref_id=manifest_evidence_ref_id,
            )
        )
    for unique_id, raw_node in sorted(nodes.items()):
        node_id = str(unique_id)
        if node_id not in captured_ids or not isinstance(raw_node, dict):
            continue
        resource_type = str(raw_node.get("resource_type", ""))
        depends = raw_node.get("depends_on")
        dependency_ids = depends.get("nodes", ()) if isinstance(depends, dict) else ()
        for dependency in sorted(map(str, dependency_ids)):
            endpoint = _dbt_dependency_endpoint(
                dependency, captured_ids=captured_ids, external_asset_ids=external
            )
            if endpoint is None:
                continue
            relationships.append(
                PendingRelationshipCapture(
                    capture_key=f"dbt-edge:{node_id}:{dependency}",
                    kind=(
                        TwinRelationshipKind.TESTS
                        if resource_type == "test"
                        else TwinRelationshipKind.TRANSFORMS_FROM
                    ),
                    from_capture_key=_dbt_key(node_id),
                    **endpoint,
                    source_authority=source_authority,
                    confidence=1,
                    attributes={"declared": True},
                    observed_at=observed_at,
                    evidence_ref_id=manifest_evidence_ref_id,
                )
            )
    if run_results is not None:
        if run_results_evidence_ref_id is None:
            raise ValueError("run_results evidence reference is required")
        for node_result in node_results_from_run_results(run_results):
            unique_id = _find_unique_id(nodes, node_result.model, "model")
            if unique_id is None or unique_id not in captured_ids:
                continue
            observations.append(
                PendingObservationCapture(
                    subject_capture_key=_dbt_key(unique_id),
                    kind=TwinObservationKind.EXECUTION_RESULT,
                    source_authority=source_authority,
                    value=node_result.model_dump(mode="json"),
                    observed_at=observed_at,
                    fresh_until=fresh_until,
                    confidence=1,
                    evidence_ref_id=run_results_evidence_ref_id,
                )
            )
        for test_result in test_results_from_run_results(run_results):
            unique_id = _find_unique_id(nodes, test_result.test_name, "test")
            if unique_id is None or unique_id not in captured_ids:
                continue
            observations.append(
                PendingObservationCapture(
                    subject_capture_key=_dbt_key(unique_id),
                    kind=TwinObservationKind.TEST_RESULT,
                    source_authority=source_authority,
                    value=test_result.model_dump(mode="json"),
                    observed_at=observed_at,
                    fresh_until=fresh_until,
                    confidence=1,
                    evidence_ref_id=run_results_evidence_ref_id,
                )
            )
    return TwinCaptureBatch(
        assets=tuple(assets),
        relationships=tuple(relationships),
        observations=tuple(observations),
    )


def capture_profile_observations(
    *,
    result: ProfilingRunResult,
    asset_ids_by_locator: dict[tuple[str, ...], UUID],
    source_authority: SourceAuthorityRef,
    evidence_ref_id: UUID,
    observed_at: datetime,
    fresh_until: datetime,
) -> tuple[PendingObservationCapture, ...]:
    """Persist only aggregate DE006 facts; samples and top values are deliberately omitted."""
    observations: list[PendingObservationCapture] = []
    for profile in sorted(result.profiles, key=lambda item: item.asset.address):
        asset_id = asset_ids_by_locator.get(profile.asset.address)
        if asset_id is None:
            raise ValueError(f"profile subject is not in Twin: {profile.asset.address}")
        observations.append(
            PendingObservationCapture(
                subject_asset_id=asset_id,
                kind=TwinObservationKind.PROFILE_SUMMARY,
                source_authority=source_authority,
                value={
                    "fixture_version": profile.fixture_version,
                    "profile_id": str(profile.profile_id),
                    "row_count": profile.row_count,
                    "sampled": profile.sampled,
                    "columns": [
                        {
                            "name": item.name,
                            "null_ratio": item.null_ratio,
                            "distinct_ratio": item.distinct_ratio,
                            "inferred_semantic": item.inferred_semantic,
                        }
                        for item in profile.columns
                    ],
                    "candidate_keys": [
                        item.model_dump(mode="json") for item in profile.candidate_keys
                    ],
                    "key_evidence": [item.model_dump(mode="json") for item in profile.key_evidence],
                    "duplicate_evidence": [
                        item.model_dump(mode="json") for item in profile.duplicate_evidence
                    ],
                    "duplicate_groups_estimate": profile.duplicate_groups_estimate,
                    "numeric_ranges": [
                        item.model_dump(mode="json") for item in profile.numeric_ranges
                    ],
                    "column_types": [list(item) for item in profile.column_types],
                    "masking": profile.masking.model_dump(mode="json"),
                },
                observed_at=observed_at,
                fresh_until=fresh_until,
                confidence=1,
                evidence_ref_id=evidence_ref_id,
            )
        )
    return tuple(observations)


def _snowflake_dataset_key(locator: tuple[str, ...]) -> str:
    return "snowflake:dataset:" + ".".join(locator)


def _snowflake_field_key(locator: tuple[str, ...], column: str) -> str:
    return "snowflake:field:" + ".".join((*locator, column))


def _dbt_key(unique_id: str) -> str:
    return f"dbt:{unique_id}"


def _dbt_locator(node: dict[str, Any], unique_id: str) -> tuple[str, ...]:
    database = node.get("database")
    schema = node.get("schema")
    alias = node.get("alias") or node.get("name")
    physical = tuple(str(item) for item in (database, schema, alias) if item)
    return physical or (unique_id,)


def _dbt_node_attributes(
    node: dict[str, Any],
    unique_id: str,
    manifest_identity: dict[str, str],
) -> dict[str, Any]:
    config = node.get("config")
    checksum = node.get("checksum")
    return {
        "unique_id": unique_id,
        "name": str(node.get("name") or unique_id),
        "package_name": node.get("package_name"),
        "original_file_path": node.get("original_file_path"),
        "relation_name": node.get("relation_name"),
        "materialized": config.get("materialized") if isinstance(config, dict) else None,
        "checksum": checksum if isinstance(checksum, dict) else None,
        "manifest_identity": manifest_identity,
    }


def _manifest_identity(manifest: dict[str, Any]) -> dict[str, str]:
    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("manifest.json missing metadata identity")
    keys = ("dbt_schema_version", "project_id", "invocation_id", "generated_at")
    identity = {key: str(metadata[key]) for key in keys if metadata.get(key) is not None}
    if "dbt_schema_version" not in identity or "project_id" not in identity:
        raise ValueError("manifest identity requires dbt_schema_version and project_id")
    return identity


def _dbt_dependency_endpoint(
    dependency: str,
    *,
    captured_ids: set[str],
    external_asset_ids: dict[str, UUID],
) -> dict[str, Any] | None:
    if dependency in captured_ids:
        return {"to_capture_key": _dbt_key(dependency)}
    external_id = external_asset_ids.get(dependency)
    if external_id is not None:
        return {"to_asset_id": external_id}
    return None


def _find_unique_id(nodes: dict[str, Any], name: str, resource_type: str) -> str | None:
    for unique_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        if node.get("resource_type") != resource_type:
            continue
        if str(node.get("name") or unique_id.split(".")[-1]) == name:
            return str(unique_id)
    return None


__all__ = [
    "PendingAssetCapture",
    "PendingObservationCapture",
    "PendingRelationshipCapture",
    "TwinCaptureBatch",
    "capture_dbt_artifacts",
    "capture_profile_observations",
    "capture_snowflake_metadata",
]
