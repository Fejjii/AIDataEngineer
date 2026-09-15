from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from aide.domain.repair import (
    MAX_APPLIED_REPAIRS_PER_TASK,
    MAX_APPLIED_REPAIRS_PER_WORKFLOW,
    MAX_POST_REPAIR_REVALIDATIONS,
    MAX_RECURSIVE_REPAIRS,
    MAX_REPAIR_PROPOSALS,
    RepairBlockReason,
    RepairEventKind,
)
from aide.repair.budget import (
    application_exhausted,
    block_reason_for_action,
    proposals_exhausted,
    recursive_forbidden,
    revalidation_exhausted,
    snapshot_from_events,
)


def test_interview_mvp_repair_limits() -> None:
    assert MAX_REPAIR_PROPOSALS == 2
    assert MAX_APPLIED_REPAIRS_PER_TASK == 1
    assert MAX_APPLIED_REPAIRS_PER_WORKFLOW == 1
    assert MAX_POST_REPAIR_REVALIDATIONS == 1
    assert MAX_RECURSIVE_REPAIRS == 0
    assert not proposals_exhausted(1)
    assert proposals_exhausted(2)
    assert not application_exhausted(0)
    assert application_exhausted(1)
    assert not revalidation_exhausted(0)
    assert revalidation_exhausted(1)
    assert recursive_forbidden(False)
    assert recursive_forbidden(True)


def test_snapshot_from_events_is_authoritative_for_task_and_workflow() -> None:
    task = uuid4()
    other = uuid4()
    events = (
        SimpleNamespace(event_kind=RepairEventKind.PROPOSAL, task_id=task),
        SimpleNamespace(event_kind="PROPOSAL", task_id=task),
        SimpleNamespace(event_kind="APPLICATION", task_id=task),
        SimpleNamespace(event_kind="APPLICATION", task_id=other),
        SimpleNamespace(event_kind="REVALIDATION", task_id=task),
        SimpleNamespace(event_kind="APPLICATION", task_id=None),
    )
    snapshot = snapshot_from_events(events, task_id=task)
    assert snapshot.proposal_count == 2
    assert snapshot.applied_count == 3
    assert snapshot.applied_count_for_task == 2
    assert snapshot.post_repair_revalidation_count == 1
    assert block_reason_for_action(snapshot, "propose") == RepairBlockReason.BUDGET_EXCEEDED.value
    assert block_reason_for_action(snapshot, "apply") == RepairBlockReason.SECOND_REPAIR.value
    assert (
        block_reason_for_action(snapshot, "revalidate") == RepairBlockReason.BUDGET_EXCEEDED.value
    )
    empty = snapshot_from_events(())
    assert empty.proposal_count == 0
    assert empty.applied_count == 0
    assert empty.applied_count_for_task == 0
    assert block_reason_for_action(empty, "propose") is None
    assert block_reason_for_action(empty, "apply") is None
    assert block_reason_for_action(empty, "revalidate") is None
