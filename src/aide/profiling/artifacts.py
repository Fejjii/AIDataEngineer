"""UI-independent typed profiling artifacts for later modelling."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.capabilities.io import CandidateKey, ProfileColumn, RelationshipCandidate
from aide.domain.sql import AssetRef


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MaskingState(FrozenModel):
    pii_columns: tuple[str, ...] = ()
    samples_masked: bool
    top_values_masked: bool
    raw_pii_persisted: bool = False


class KeyEvidence(FrozenModel):
    columns: tuple[str, ...]
    uniqueness_ratio: float = Field(ge=0, le=1)
    null_ratio: float = Field(ge=0, le=1)
    expression: str | None = None
    is_candidate: bool
    reason: str


class DuplicateEvidence(FrozenModel):
    columns: tuple[str, ...]
    expression: str | None = None
    duplicate_groups_estimate: int = Field(ge=0)
    extra_row_estimate: int = Field(ge=0)
    uniqueness_ratio: float = Field(ge=0, le=1)
    reason: str


class NumericRange(FrozenModel):
    column: str
    min_value: Any | None = None
    max_value: Any | None = None
    mean: float | None = None


class DatasetProfileArtifact(FrozenModel):
    fixture_version: str
    asset: AssetRef
    profile_id: UUID
    describe_snapshot_id: UUID | None
    capability_profile_id: UUID | None
    row_count: int
    sampled: bool
    columns: tuple[ProfileColumn, ...]
    candidate_keys: tuple[CandidateKey, ...]
    key_evidence: tuple[KeyEvidence, ...]
    duplicate_evidence: tuple[DuplicateEvidence, ...]
    duplicate_groups_estimate: int = Field(ge=0)
    masking: MaskingState
    numeric_ranges: tuple[NumericRange, ...] = ()
    column_types: tuple[tuple[str, str], ...] = ()


class RelationshipEvidence(FrozenModel):
    candidate: RelationshipCandidate
    reason: str
    missing_count: int = Field(ge=0)
    child_distinct: int = Field(ge=0)
    name_related: bool
    measured: bool = False


class SampleArtifact(FrozenModel):
    fixture_version: str
    asset: AssetRef
    sample_id: UUID
    row_count: int
    masked_columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    masking: MaskingState
    bytes_used: int = Field(ge=0)


class ProfilingFact(FrozenModel):
    fact_id: str
    asset: AssetRef | None = None
    columns: tuple[str, ...] = ()
    metric: str
    value: float | int | str | bool | None
    detail: str


class BudgetUsage(FrozenModel):
    queries: int
    pairs: int
    elapsed_seconds: float
    max_queries: int
    max_pairs: int
    max_seconds: int
    sample_n: int


class ProfilingSummary(FrozenModel):
    """Structured planner input for DE007. Contains facts, not modelling decisions."""

    fixture_version: str
    connector_id: str
    assets: tuple[AssetRef, ...]
    excluded_addresses: tuple[tuple[str, ...], ...] = ()
    facts: tuple[ProfilingFact, ...]
    relationship_count: int
    sample_asset_count: int
    budget: BudgetUsage
    masking_applied: bool
    truncated_tasks: bool = False


class ProfilingRunResult(FrozenModel):
    fixture_version: str
    duration_seconds: float
    profiles: tuple[DatasetProfileArtifact, ...]
    relationships: tuple[RelationshipEvidence, ...]
    samples: tuple[SampleArtifact, ...]
    summary: ProfilingSummary
    relationships_id: UUID
    masking: MaskingState
