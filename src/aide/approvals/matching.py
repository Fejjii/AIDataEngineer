"""Deterministic approval matching against the full typed subject binding."""

from __future__ import annotations

from datetime import datetime

from aide.domain.approvals import (
    ApprovalRecord,
    ApprovalSubject,
    BudgetIncreaseApproval,
    DesignApproval,
    OperationApproval,
    OperationBinding,
    approval_is_effective,
)


class ApprovalMatchError(ValueError):
    pass


def match_operation_approval(
    record: ApprovalRecord,
    binding: OperationBinding,
    *,
    now: datetime,
) -> bool:
    subject = record.subject
    if not isinstance(subject, OperationApproval):
        return False
    if not approval_is_effective(record, now):
        return False
    return subject.covers_operation(binding)


def match_design_approval(
    record: ApprovalRecord,
    expected: DesignApproval,
    *,
    now: datetime,
) -> bool:
    subject = record.subject
    if not isinstance(subject, DesignApproval):
        return False
    if not approval_is_effective(record, now):
        return False
    return (
        subject.design_artifact_hash == expected.design_artifact_hash
        and subject.validation_report_hash == expected.validation_report_hash
        and subject.invariant_hashes == expected.invariant_hashes
    )


def match_budget_approval(
    record: ApprovalRecord,
    expected: BudgetIncreaseApproval,
    *,
    now: datetime,
) -> bool:
    subject = record.subject
    if not isinstance(subject, BudgetIncreaseApproval):
        return False
    if not approval_is_effective(record, now):
        return False
    return (
        subject.budget_scope is expected.budget_scope
        and subject.ledger_version == expected.ledger_version
        and subject.unit is expected.unit
        and subject.prior_cap == expected.prior_cap
        and subject.authorized_new_cap == expected.authorized_new_cap
        and subject.authorized_delta == expected.authorized_delta
    )


def simultaneous_subjects_approved(
    records: tuple[ApprovalRecord, ...],
    required: tuple[ApprovalSubject, ...],
    *,
    now: datetime,
    operation_binding: OperationBinding | None = None,
) -> bool:
    """Execution resumes only when every mandatory subject is approved and valid."""
    if not required:
        return True
    for subject in required:
        if not _subject_satisfied(records, subject, now=now, operation_binding=operation_binding):
            return False
    return True


def _subject_satisfied(
    records: tuple[ApprovalRecord, ...],
    subject: ApprovalSubject,
    *,
    now: datetime,
    operation_binding: OperationBinding | None,
) -> bool:
    for record in records:
        if isinstance(subject, OperationApproval):
            binding = operation_binding or subject.as_binding()
            matched = match_operation_approval(record, binding, now=now)
        elif isinstance(subject, DesignApproval):
            matched = match_design_approval(record, subject, now=now)
        elif isinstance(subject, BudgetIncreaseApproval):
            matched = match_budget_approval(record, subject, now=now)
        else:
            matched = False
        if matched:
            return True
    return False
