"""Deterministic join-candidate ranking from profile metadata. No fixture pair lists."""

from __future__ import annotations

from dataclasses import dataclass

from aide.capabilities.io import ProfileColumn
from aide.domain.sql import AssetRef
from aide.profiling.artifacts import DatasetProfileArtifact
from aide.profiling.semantics import names_related, types_compatible

JOIN_SEMANTICS = frozenset({"ID", "CODE"})
INCLUSION_FLOOR = 0.5


@dataclass(frozen=True, slots=True)
class JoinCandidateSpec:
    from_asset: AssetRef
    from_column: str
    to_asset: AssetRef
    to_column: str
    name_related: bool
    from_uniqueness: float
    to_uniqueness: float
    rank_score: float


def join_rank_score(
    *,
    name_related: bool,
    from_semantic: str | None,
    to_semantic: str | None,
    from_uniqueness: float,
    to_uniqueness: float,
) -> float:
    score = 0.0
    if name_related:
        score += 3.0
    if from_semantic == to_semantic and from_semantic in JOIN_SEMANTICS:
        score += 0.5
    score += min(max(to_uniqueness, 0.0), 1.0)
    score += min(max(1.0 - from_uniqueness, 0.0), 1.0) * 0.25
    return round(score, 6)


def _type_map(profile: DatasetProfileArtifact) -> dict[str, str]:
    return {name.upper(): dtype for name, dtype in profile.column_types}


def _column_uniqueness(column: ProfileColumn) -> float:
    return column.distinct_ratio


def rank_join_candidates(
    profiles: tuple[DatasetProfileArtifact, ...],
) -> tuple[JoinCandidateSpec, ...]:
    """Rank generic join pairs from semantics, types, names, and uniqueness."""
    specs: list[JoinCandidateSpec] = []
    for left in profiles:
        left_types = _type_map(left)
        for right in profiles:
            if left.asset.address == right.asset.address:
                continue
            right_types = _type_map(right)
            for left_col in left.columns:
                if left_col.inferred_semantic not in JOIN_SEMANTICS:
                    continue
                for right_col in right.columns:
                    if right_col.inferred_semantic not in JOIN_SEMANTICS:
                        continue
                    left_type = left_types.get(left_col.name.upper(), "VARCHAR")
                    right_type = right_types.get(right_col.name.upper(), "VARCHAR")
                    if not types_compatible(left_type, right_type):
                        continue
                    related = names_related(left_col.name, right_col.name)
                    from_uniq = _column_uniqueness(left_col)
                    to_uniq = _column_uniqueness(right_col)
                    specs.append(
                        JoinCandidateSpec(
                            from_asset=left.asset,
                            from_column=left_col.name,
                            to_asset=right.asset,
                            to_column=right_col.name,
                            name_related=related,
                            from_uniqueness=from_uniq,
                            to_uniqueness=to_uniq,
                            rank_score=join_rank_score(
                                name_related=related,
                                from_semantic=left_col.inferred_semantic,
                                to_semantic=right_col.inferred_semantic,
                                from_uniqueness=from_uniq,
                                to_uniqueness=to_uniq,
                            ),
                        )
                    )
    specs.sort(
        key=lambda item: (
            -item.rank_score,
            item.from_asset.address,
            item.from_column,
            item.to_asset.address,
            item.to_column,
        )
    )
    return tuple(specs)


def select_join_candidates_for_measurement(
    profiles: tuple[DatasetProfileArtifact, ...],
    *,
    max_pairs: int,
) -> tuple[JoinCandidateSpec, ...]:
    """Prefer name-related ID/CODE pairs, then fill remaining slots by rank."""
    if max_pairs < 1:
        return ()
    ranked = rank_join_candidates(profiles)
    related = tuple(item for item in ranked if item.name_related)
    other = tuple(item for item in ranked if not item.name_related)
    return (*related, *other)[:max_pairs]
