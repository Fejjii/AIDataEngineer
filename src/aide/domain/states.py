"""Workflow, cancellation, task, and attempt state contracts."""

from __future__ import annotations

from collections import deque
from enum import Enum


class WorkflowState(str, Enum):
    RECEIVED = "RECEIVED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    PLANNING = "PLANNING"
    DISCOVERY = "DISCOVERY"
    PROFILING = "PROFILING"
    DESIGN = "DESIGN"
    GENERATION = "GENERATION"
    POLICY_CHECK = "POLICY_CHECK"
    EXECUTION = "EXECUTION"
    VALIDATION = "VALIDATION"
    REPAIR = "REPAIR"
    DELIVERY = "DELIVERY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    MONITORING = "MONITORING"
    BLOCKED = "BLOCKED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CancellationState(str, Enum):
    NONE = "NONE"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"


class PhaseRunStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    REDUCING = "REDUCING"
    SUCCEEDED = "SUCCEEDED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskState(str, Enum):
    TEMPLATE_PENDING = "TEMPLATE_PENDING"
    MATERIALIZED = "MATERIALIZED"
    READY = "READY"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RETRY_WAIT = "RETRY_WAIT"
    RECONCILING = "RECONCILING"
    PARKED = "PARKED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class DispatchState(str, Enum):
    NOT_DISPATCHED = "NOT_DISPATCHED"
    DISPATCHED = "DISPATCHED"
    REJECTED_NO_EFFECT = "REJECTED_NO_EFFECT"
    OUTCOME_AMBIGUOUS = "OUTCOME_AMBIGUOUS"


class AttemptOutcome(str, Enum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    RECOVERED = "RECOVERED"
    AMBIGUOUS = "AMBIGUOUS"
    CANCELLED = "CANCELLED"


TERMINAL_WORKFLOW_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    }
)

# Authoritative legal transitions from docs/STATE_MODEL.md §3.
# Guards live with the scheduler; this set is the structural contract.
LEGAL_TRANSITIONS: frozenset[tuple[WorkflowState, WorkflowState]] = frozenset(
    {
        (WorkflowState.RECEIVED, WorkflowState.CLARIFICATION_REQUIRED),
        (WorkflowState.RECEIVED, WorkflowState.PLANNING),
        (WorkflowState.RECEIVED, WorkflowState.BLOCKED),
        (WorkflowState.CLARIFICATION_REQUIRED, WorkflowState.RECEIVED),
        (WorkflowState.CLARIFICATION_REQUIRED, WorkflowState.PLANNING),
        (WorkflowState.CLARIFICATION_REQUIRED, WorkflowState.CANCEL_REQUESTED),
        (WorkflowState.PLANNING, WorkflowState.DISCOVERY),
        (WorkflowState.PLANNING, WorkflowState.PROFILING),
        (WorkflowState.PLANNING, WorkflowState.DESIGN),
        (WorkflowState.PLANNING, WorkflowState.GENERATION),
        (WorkflowState.PLANNING, WorkflowState.DELIVERY),
        (WorkflowState.PLANNING, WorkflowState.BLOCKED),
        (WorkflowState.DISCOVERY, WorkflowState.PLANNING),
        (WorkflowState.PROFILING, WorkflowState.PLANNING),
        (WorkflowState.DESIGN, WorkflowState.APPROVAL_REQUIRED),
        (WorkflowState.DESIGN, WorkflowState.CLARIFICATION_REQUIRED),
        (WorkflowState.DESIGN, WorkflowState.PLANNING),
        (WorkflowState.GENERATION, WorkflowState.REPAIR),
        (WorkflowState.GENERATION, WorkflowState.POLICY_CHECK),
        (WorkflowState.POLICY_CHECK, WorkflowState.FAILED),
        (WorkflowState.POLICY_CHECK, WorkflowState.BLOCKED),
        (WorkflowState.POLICY_CHECK, WorkflowState.APPROVAL_REQUIRED),
        (WorkflowState.POLICY_CHECK, WorkflowState.EXECUTION),
        (WorkflowState.EXECUTION, WorkflowState.VALIDATION),
        (WorkflowState.VALIDATION, WorkflowState.REPAIR),
        (WorkflowState.VALIDATION, WorkflowState.PLANNING),
        (WorkflowState.VALIDATION, WorkflowState.BLOCKED),
        (WorkflowState.REPAIR, WorkflowState.GENERATION),
        (WorkflowState.REPAIR, WorkflowState.EXECUTION),
        (WorkflowState.REPAIR, WorkflowState.BLOCKED),
        (WorkflowState.DELIVERY, WorkflowState.APPROVAL_REQUIRED),
        (WorkflowState.DELIVERY, WorkflowState.MONITORING),
        (WorkflowState.DELIVERY, WorkflowState.COMPLETED),
        (WorkflowState.DELIVERY, WorkflowState.FAILED),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.DESIGN),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.EXECUTION),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.DELIVERY),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.PLANNING),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.COMPLETED),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.BLOCKED),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.FAILED),
        (WorkflowState.APPROVAL_REQUIRED, WorkflowState.CANCEL_REQUESTED),
        (WorkflowState.MONITORING, WorkflowState.COMPLETED),
        (WorkflowState.BLOCKED, WorkflowState.PLANNING),
        (WorkflowState.BLOCKED, WorkflowState.EXECUTION),
        (WorkflowState.BLOCKED, WorkflowState.DISCOVERY),
        (WorkflowState.BLOCKED, WorkflowState.PROFILING),
        (WorkflowState.BLOCKED, WorkflowState.DESIGN),
        (WorkflowState.BLOCKED, WorkflowState.GENERATION),
        (WorkflowState.BLOCKED, WorkflowState.POLICY_CHECK),
        (WorkflowState.BLOCKED, WorkflowState.VALIDATION),
        (WorkflowState.BLOCKED, WorkflowState.REPAIR),
        (WorkflowState.BLOCKED, WorkflowState.DELIVERY),
        (WorkflowState.BLOCKED, WorkflowState.CANCEL_REQUESTED),
        (WorkflowState.BLOCKED, WorkflowState.FAILED),
        (WorkflowState.CANCEL_REQUESTED, WorkflowState.CANCELLING),
        (WorkflowState.CANCELLING, WorkflowState.CANCELLED),
    }
)

# ANY non-terminal → CANCEL_REQUESTED / BLOCKED / FAILED (except already cancelling).
_NON_CANCEL_STATES = frozenset(
    {
        WorkflowState.CANCEL_REQUESTED,
        WorkflowState.CANCELLING,
        *TERMINAL_WORKFLOW_STATES,
    }
)

LEGAL_TRANSITIONS = (
    LEGAL_TRANSITIONS
    | frozenset(
        (state, WorkflowState.CANCEL_REQUESTED)
        for state in WorkflowState
        if state not in _NON_CANCEL_STATES
    )
    | frozenset(
        (state, WorkflowState.BLOCKED)
        for state in WorkflowState
        if state not in TERMINAL_WORKFLOW_STATES | {WorkflowState.BLOCKED}
    )
    | frozenset(
        (state, WorkflowState.FAILED)
        for state in WorkflowState
        if state not in TERMINAL_WORKFLOW_STATES
    )
)


def is_reachable(start: WorkflowState = WorkflowState.RECEIVED) -> frozenset[WorkflowState]:
    seen: set[WorkflowState] = {start}
    queue: deque[WorkflowState] = deque([start])
    edges: dict[WorkflowState, set[WorkflowState]] = {src: set() for src, _ in LEGAL_TRANSITIONS}
    for src, dst in LEGAL_TRANSITIONS:
        edges.setdefault(src, set()).add(dst)
    while queue:
        current = queue.popleft()
        for nxt in edges.get(current, ()):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return frozenset(seen)


def nonterminal_has_exit(state: WorkflowState) -> bool:
    if state in TERMINAL_WORKFLOW_STATES:
        return True
    return any(src == state for src, _ in LEGAL_TRANSITIONS)
