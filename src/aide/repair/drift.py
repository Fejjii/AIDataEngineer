"""Build authoritative DriftEvidence from Snowflake describe/detect outputs."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid4

from aide.capabilities.io import ColumnSpec, DetectSchemaDriftOutput
from aide.domain.artifacts import ExecutionMode
from aide.domain.identity import canonical_json_bytes
from aide.domain.repair import DriftColumn, DriftEvidence
from aide.domain.sql import AssetRef
from aide.domain.twin import SourceAuthorityRef
from aide.repair.allowlist import is_accepted_authority, is_accepted_mapping


def as_drift_column(column: ColumnSpec) -> DriftColumn:
    return DriftColumn(
        name=column.name,
        data_type=column.data_type,
        nullable=column.nullable,
        ordinal=column.ordinal,
    )


def build_drift_evidence(
    *,
    asset: AssetRef,
    detect: DetectSchemaDriftOutput,
    current_columns: tuple[ColumnSpec, ...],
    baseline_columns: tuple[ColumnSpec, ...],
    source_authority: SourceAuthorityRef,
    observed_at: datetime,
    fresh_until: datetime,
    twin_snapshot_id: UUID,
    execution_mode: ExecutionMode,
    producer_operation_key: str | None,
    from_column: str,
    to_column: str,
) -> DriftEvidence:
    added = tuple(as_drift_column(item) for item in detect.added)
    removed = tuple(as_drift_column(item) for item in detect.removed)
    old = next(
        (item for item in baseline_columns if item.name.upper() == from_column.upper()),
        None,
    )
    new = next((item for item in current_columns if item.name.upper() == to_column.upper()), None)
    type_changed = tuple((item.name, item.from_type, item.to_type) for item in detect.type_changed)
    body = {
        "asset": list(asset.address),
        "added": [item.model_dump(mode="json") for item in added],
        "removed": [item.model_dump(mode="json") for item in removed],
        "from_column": from_column,
        "to_column": to_column,
    }
    digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    authoritative = (
        is_accepted_authority(source_authority.authority_id)
        and is_accepted_mapping(from_column, to_column)
        and detect.drifted
        and old is not None
        and new is not None
    )
    return DriftEvidence(
        observation_id=uuid4(),
        evidence_ref_id=uuid4(),
        asset=asset,
        from_column=from_column,
        to_column=to_column,
        old_data_type=old.data_type if old is not None else "",
        new_data_type=new.data_type if new is not None else "",
        drifted=detect.drifted,
        added=added,
        removed=removed,
        type_changed=type_changed,
        observed_at=observed_at,
        fresh_until=fresh_until,
        source_authority=source_authority,
        authoritative=authoritative,
        sha256=digest,
        execution_mode=execution_mode,
        twin_snapshot_id=twin_snapshot_id,
        producer_operation_key=producer_operation_key,
    )


__all__ = ["as_drift_column", "build_drift_evidence"]
