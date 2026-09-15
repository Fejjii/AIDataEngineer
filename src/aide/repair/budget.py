"""Append-only repair budget counting over persisted events."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from aide.domain.repair import (
    MAX_APPLIED_REPAIRS_PER_TASK,
    MAX_APPLIED_REPAIRS_PER_WORKFLOW,
    MAX_POST_REPAIR_REVALIDATIONS,
    MAX_RECURSIVE_REPAIRS,
    MAX_REPAIR_PROPOSALS,
    RepairBlockReason,
    RepairBudgetSnapshot,
    RepairEventKind,
)


def snapshot_from_counts(
    *,
    proposal_count: int,
    applied_count: int,
    post_repair_revalidation_count: int,
    applied_count_for_task: int | None = None,
    recursive_requested: bool = False,
    permission_changed: bool = False,
    target_changed: bool = False,
    source_data_mutated: bool = False,
) -> RepairBudgetSnapshot:
    return RepairBudgetSnapshot(
        proposal_count=proposal_count,
        applied_count=applied_count,
        applied_count_for_task=(
            applied_count if applied_count_for_task is None else applied_count_for_task
        ),
        post_repair_revalidation_count=post_repair_revalidation_count,
        recursive_requested=recursive_requested,
        permission_changed=permission_changed,
        target_changed=target_changed,
        source_data_mutated=source_data_mutated,
    )


def snapshot_from_events(
    events: Iterable[Any],
    *,
    task_id: UUID | None = None,
    recursive_requested: bool = False,
    permission_changed: bool = False,
    target_changed: bool = False,
    source_data_mutated: bool = False,
) -> RepairBudgetSnapshot:
    """Derive the repair budget from persisted RepairEvent records only."""
    proposal_count = 0
    applied_count = 0
    applied_count_for_task = 0
    post_repair_revalidation_count = 0
    for item in events:
        kind = _event_kind(item)
        if kind == RepairEventKind.PROPOSAL.value:
            proposal_count += 1
        elif kind == RepairEventKind.APPLICATION.value:
            applied_count += 1
            event_task = getattr(item, "task_id", None)
            if task_id is None or event_task is None or event_task == task_id:
                applied_count_for_task += 1
        elif kind == RepairEventKind.REVALIDATION.value:
            post_repair_revalidation_count += 1
    if task_id is None:
        applied_count_for_task = applied_count
    return RepairBudgetSnapshot(
        proposal_count=proposal_count,
        applied_count=applied_count,
        applied_count_for_task=applied_count_for_task,
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


def block_reason_for_action(snapshot: RepairBudgetSnapshot, action: str) -> str | None:
    """Return a block reason when a persisted budget forbids the next repair action."""
    if snapshot.recursive_requested:
        return RepairBlockReason.RECURSIVE_REPAIR.value
    if action == "propose" and proposals_exhausted(snapshot.proposal_count):
        return RepairBlockReason.BUDGET_EXCEEDED.value
    if action == "apply" and (
        snapshot.applied_count >= MAX_APPLIED_REPAIRS_PER_WORKFLOW
        or snapshot.applied_count_for_task >= MAX_APPLIED_REPAIRS_PER_TASK
    ):
        return RepairBlockReason.SECOND_REPAIR.value
    if action == "revalidate" and revalidation_exhausted(snapshot.post_repair_revalidation_count):
        return RepairBlockReason.BUDGET_EXCEEDED.value
    return None


def _event_kind(item: Any) -> str:
    kind = getattr(item, "event_kind", item)
    if isinstance(kind, RepairEventKind):
        return kind.value
    return str(kind)


__all__ = [
    "application_exhausted",
    "block_reason_for_action",
    "count_kind",
    "proposals_exhausted",
    "revalidation_exhausted",
    "recursive_forbidden",
    "snapshot_from_counts",
    "snapshot_from_events",
]
