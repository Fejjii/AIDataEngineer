"""Column-drift comparison used by detect_schema_drift."""

from __future__ import annotations

from difflib import SequenceMatcher

from aide.capabilities.io import (
    ColumnSpec,
    ColumnTypeChange,
    DetectSchemaDriftOutput,
    RenamedColumnCandidate,
)


def compare_columns(
    current: tuple[ColumnSpec, ...],
    baseline: tuple[ColumnSpec, ...],
) -> DetectSchemaDriftOutput:
    current_by_name = {item.name: item for item in current}
    baseline_by_name = {item.name: item for item in baseline}
    added = tuple(item for item in current if item.name not in baseline_by_name)
    removed = tuple(item for item in baseline if item.name not in current_by_name)
    type_changed = tuple(
        ColumnTypeChange(
            name=name,
            from_type=baseline_by_name[name].data_type,
            to_type=current_by_name[name].data_type,
        )
        for name in current_by_name
        if name in baseline_by_name
        and current_by_name[name].data_type != baseline_by_name[name].data_type
    )
    renamed: list[RenamedColumnCandidate] = []
    unused_added = list(added)
    for removed_col in removed:
        best: RenamedColumnCandidate | None = None
        for candidate in unused_added:
            if candidate.data_type != removed_col.data_type:
                continue
            position_bonus = 0.15 if candidate.ordinal == removed_col.ordinal else 0.0
            name_score = SequenceMatcher(None, removed_col.name, candidate.name).ratio()
            confidence = min(1.0, name_score + position_bonus)
            if confidence < 0.55:
                continue
            if best is None or confidence > best.confidence:
                best = RenamedColumnCandidate(
                    from_name=removed_col.name,
                    to_name=candidate.name,
                    confidence=round(confidence, 4),
                )
        if best is not None:
            renamed.append(best)
            unused_added = [item for item in unused_added if item.name != best.to_name]
    drifted = bool(added or removed or type_changed)
    return DetectSchemaDriftOutput(
        drifted=drifted,
        added=added,
        removed=removed,
        type_changed=type_changed,
        renamed_candidates=tuple(renamed),
    )
