"""Append-only repair budget counting over persisted events."""

from __future__ import annotations

from aide.domain.repair import (
    MAX_APPLIED_REPAIRS_PER_TASK,
    MAX_APPLIED_REPAIRS_PER_WORKFLOW,
    MAX_POST_REPAIR_REVALIDATIONS,
    MAX_RECURSIVE_REPAIRS,
    MAX_REPAIR_PROPOSALS,
    RepairBudgetSnapshot,
    RepairEventKind,
)


def snapshot_from_counts(
    *,
    proposal_count: int,
    applied_count: int,
    post_repair_revalidation_count: int,
    recursive_requested: bool = False,
    permission_changed: bool = False,
    target_changed: bool = False,
    source_data_mutated: bool = False,
) -> RepairBudgetSnapshot:
    return RepairBudgetSnapshot(
        proposal_count=proposal_count,
        applied_count=applied_count,
        post_repair_revalidation_count=post_repair_revalidation_count,
        recursive_requested=recursive_requested,
        permission_changed=permission_changed,
        target_changed=target_changed,
        source_data_mutated=source_data_mutated,
    )


def count_kind(events: tuple[str, ...], kind: RepairEventKind) -> int:
    return sum(1 for item in events if item == kind.value)


def proposals_exhausted(proposal_count: int) -> bool:
    return proposal_count >= MAX_REPAIR_PROPOSALS


def application_exhausted(applied_count: int) -> bool:
    return (
        applied_count >= MAX_APPLIED_REPAIRS_PER_TASK
        or applied_count >= MAX_APPLIED_REPAIRS_PER_WORKFLOW
    )


def revalidation_exhausted(count: int) -> bool:
    return count >= MAX_POST_REPAIR_REVALIDATIONS


def recursive_forbidden(requested: bool) -> bool:
    return requested or MAX_RECURSIVE_REPAIRS == 0


__all__ = [
    "application_exhausted",
    "count_kind",
    "proposals_exhausted",
    "revalidation_exhausted",
    "recursive_forbidden",
    "snapshot_from_counts",
]
