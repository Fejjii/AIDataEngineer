"""Legal APPROVAL_REQUIRED rejection routes."""

from __future__ import annotations

from enum import Enum

from aide.domain.approvals import (
    ApprovalSubject,
    BudgetIncreaseApproval,
    DesignApproval,
    OperationApproval,
)
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState


class TaskDisposition(str, Enum):
    CANCELLED_APPROVAL_REJECTED = "CANCELLED(APPROVAL_REJECTED)"
    FAILED = "FAILED"
    SKIPPED_APPROVAL_REJECTED = "SKIPPED(APPROVAL_REJECTED)"
    NONE = "NONE"


class ApprovalRejectionRoute:
    def __init__(
        self,
        workflow_state: WorkflowState,
        task_disposition: TaskDisposition,
        reason: str,
    ) -> None:
        self.workflow_state = workflow_state
        self.task_disposition = task_disposition
        self.reason = reason


_LEGAL_WORKFLOW_TARGETS = frozenset(
    {
        WorkflowState.PLANNING,
        WorkflowState.COMPLETED,
        WorkflowState.BLOCKED,
        WorkflowState.FAILED,
    }
)


def route_approval_rejection(
    subject: ApprovalSubject,
    *,
    documented_pr_fallback: bool = False,
    required_operation: bool = True,
) -> ApprovalRejectionRoute:
    """Subject-specific routing. Does not weaken approval semantics."""
    if isinstance(subject, DesignApproval):
        return ApprovalRejectionRoute(
            WorkflowState.PLANNING,
            TaskDisposition.NONE,
            "DESIGN_REJECTED",
        )
    if isinstance(subject, BudgetIncreaseApproval):
        return ApprovalRejectionRoute(
            WorkflowState.BLOCKED,
            TaskDisposition.NONE,
            "BUDGET_NOT_AUTHORIZED",
        )
    if isinstance(subject, OperationApproval):
        if subject.required_permission is PermissionLevel.STAGING_DEPLOY or (
            subject.target_environment is TargetEnv.STAGING
            and subject.capability_id == "deploy_staging"
        ):
            if documented_pr_fallback:
                return ApprovalRejectionRoute(
                    WorkflowState.COMPLETED,
                    TaskDisposition.CANCELLED_APPROVAL_REJECTED,
                    "STAGING_REJECTED_PR_FALLBACK",
                )
            return ApprovalRejectionRoute(
                WorkflowState.BLOCKED,
                TaskDisposition.CANCELLED_APPROVAL_REJECTED,
                "STAGING_REJECTED_NO_FALLBACK",
            )
        destructive_or_git = subject.required_permission in {
            PermissionLevel.DESTRUCTIVE,
            PermissionLevel.GIT_WRITE,
        } or subject.capability_id in {"drop_dataset", "prepare_git_change", "prepare_pull_request"}
        if destructive_or_git:
            if required_operation:
                return ApprovalRejectionRoute(
                    WorkflowState.FAILED,
                    TaskDisposition.FAILED,
                    "REQUIRED_OPERATION_REJECTED",
                )
            return ApprovalRejectionRoute(
                WorkflowState.DELIVERY
                if subject.required_permission is PermissionLevel.GIT_WRITE
                else WorkflowState.EXECUTION,
                TaskDisposition.SKIPPED_APPROVAL_REJECTED,
                "OPTIONAL_OPERATION_REJECTED",
            )
        return ApprovalRejectionRoute(
            WorkflowState.FAILED,
            TaskDisposition.FAILED,
            "REQUIRED_OPERATION_REJECTED",
        )
    raise TypeError(f"unknown approval subject {type(subject)!r}")


def assert_legal_workflow_route(route: ApprovalRejectionRoute) -> None:
    if (
        route.workflow_state not in _LEGAL_WORKFLOW_TARGETS
        and route.task_disposition is not TaskDisposition.SKIPPED_APPROVAL_REJECTED
    ):
        raise ValueError(f"illegal approval rejection workflow state {route.workflow_state}")
