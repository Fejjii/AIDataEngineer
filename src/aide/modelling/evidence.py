"""Convert profiling artifacts into capability-safe modelling evidence."""

from __future__ import annotations

from aide.capabilities.io import (
    AssetProfileEvidence,
    DuplicateEvidenceLite,
    ProfilingEvidenceSummary,
    RelationshipCandidate,
)
from aide.modelling.constants import (
    CREATED_AT_NAMES,
    LOADED_AT_NAMES,
    UPDATED_AT_NAMES,
    VALID_FROM_NAMES,
    VALID_TO_NAMES,
)
from aide.profiling.artifacts import DatasetProfileArtifact, ProfilingRunResult


def _names(values: frozenset[str], columns: tuple[str, ...]) -> bool:
    upper = {item.upper() for item in columns}
    return any(name in upper for name in values)


def _null_ratio(profile: DatasetProfileArtifact, names: frozenset[str]) -> float | None:
    for column in profile.columns:
        if column.name.upper() in names:
            return column.null_ratio
    return None


def asset_evidence(profile: DatasetProfileArtifact) -> AssetProfileEvidence:
    columns = tuple(column.name for column in profile.columns)
    if not columns and profile.column_types:
        columns = tuple(name for name, _ in profile.column_types)
    key_uniqueness: list[tuple[str, float]] = []
    composite: list[tuple[tuple[str, ...], float, bool]] = []
    for item in profile.key_evidence:
        if len(item.columns) == 1:
            key_uniqueness.append((item.columns[0], item.uniqueness_ratio))
        composite.append((item.columns, item.uniqueness_ratio, item.is_candidate))
    return AssetProfileEvidence(
        asset=profile.asset,
        row_count=profile.row_count,
        columns=columns,
        column_types=profile.column_types,
        candidate_keys=profile.candidate_keys,
        key_uniqueness=tuple(key_uniqueness),
        composite_key_uniqueness=tuple(composite),
        duplicate_groups_estimate=profile.duplicate_groups_estimate,
        has_valid_from=_names(VALID_FROM_NAMES, columns),
        has_valid_to=_names(VALID_TO_NAMES, columns),
        has_updated_at=_names(UPDATED_AT_NAMES, columns),
        has_created_at=_names(CREATED_AT_NAMES, columns),
        has_loaded_at=_names(LOADED_AT_NAMES, columns),
        updated_at_null_ratio=_null_ratio(profile, UPDATED_AT_NAMES),
        loaded_at_null_ratio=_null_ratio(profile, LOADED_AT_NAMES),
        foreign_key_columns=tuple(
            name
            for name in columns
            if name.upper().endswith("_ID") and name.upper() not in {columns[0].upper()}
        ),
    )


def duplicate_evidence(run: ProfilingRunResult) -> tuple[DuplicateEvidenceLite, ...]:
    items: list[DuplicateEvidenceLite] = []
    for profile in run.profiles:
        for item in profile.duplicate_evidence:
            items.append(
                DuplicateEvidenceLite(
                    asset=profile.asset,
                    columns=item.columns,
                    uniqueness_ratio=item.uniqueness_ratio,
                    duplicate_groups_estimate=item.duplicate_groups_estimate,
                    extra_row_estimate=item.extra_row_estimate,
                    reason=item.reason,
                )
            )
    return tuple(items)


def evidence_from_run(
    run: ProfilingRunResult,
) -> tuple[
    tuple[AssetProfileEvidence, ...],
    tuple[RelationshipCandidate, ...],
    tuple[DuplicateEvidenceLite, ...],
    ProfilingEvidenceSummary,
]:
    profiles = tuple(asset_evidence(item) for item in run.profiles)
    relationships = tuple(item.candidate for item in run.relationships)
    summary = ProfilingEvidenceSummary(
        fixture_version=run.fixture_version,
        fact_ids=tuple(item.fact_id for item in run.summary.facts),
        fact_details=tuple((item.fact_id, item.detail) for item in run.summary.facts),
        relationship_count=len(run.relationships),
        masking_applied=run.summary.masking_applied,
    )
    return profiles, relationships, duplicate_evidence(run), summary
