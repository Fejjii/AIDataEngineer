from __future__ import annotations

import pytest

from aide.domain.permissions import PermissionLevel
from aide.domain.states import (
    LEGAL_TRANSITIONS,
    TERMINAL_WORKFLOW_STATES,
    WorkflowState,
    is_reachable,
    nonterminal_has_exit,
)


def test_permission_level_has_no_ordering() -> None:
    with pytest.raises(TypeError):
        _ = PermissionLevel.READ < PermissionLevel.SECURITY
    with pytest.raises(TypeError):
        _ = PermissionLevel.READ > PermissionLevel.SECURITY
    with pytest.raises(TypeError):
        _ = PermissionLevel.READ <= PermissionLevel.DEVELOPMENT_WRITE
    with pytest.raises(TypeError):
        _ = PermissionLevel.GIT_WRITE >= PermissionLevel.READ
    with pytest.raises(TypeError):
        max(PermissionLevel.READ, PermissionLevel.SECURITY)


def test_every_workflow_state_reachable_and_nonterminal_has_exit() -> None:
    reachable = is_reachable(WorkflowState.RECEIVED)
    assert set(WorkflowState) <= set(reachable)
    for state in WorkflowState:
        assert nonterminal_has_exit(state)
    assert WorkflowState.COMPLETED in TERMINAL_WORKFLOW_STATES
    assert (WorkflowState.APPROVAL_REQUIRED, WorkflowState.PLANNING) in LEGAL_TRANSITIONS
    assert (WorkflowState.APPROVAL_REQUIRED, WorkflowState.COMPLETED) in LEGAL_TRANSITIONS
    assert (WorkflowState.APPROVAL_REQUIRED, WorkflowState.BLOCKED) in LEGAL_TRANSITIONS
    assert (WorkflowState.APPROVAL_REQUIRED, WorkflowState.FAILED) in LEGAL_TRANSITIONS
    assert (WorkflowState.EXECUTION, WorkflowState.APPROVAL_REQUIRED) in LEGAL_TRANSITIONS
