"""Typed approval matching and rejection routing contracts."""

from aide.approvals.matching import (
    ApprovalMatchError,
    match_budget_approval,
    match_design_approval,
    match_operation_approval,
    simultaneous_subjects_approved,
)
from aide.approvals.routing import (
    ApprovalRejectionRoute,
    TaskDisposition,
    route_approval_rejection,
)

__all__ = [
    "ApprovalMatchError",
    "ApprovalRejectionRoute",
    "TaskDisposition",
    "match_budget_approval",
    "match_design_approval",
    "match_operation_approval",
    "route_approval_rejection",
    "simultaneous_subjects_approved",
]
