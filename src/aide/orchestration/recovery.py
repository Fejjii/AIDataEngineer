"""Bounded four-way reconciliation for ambiguous side effects."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.domain.identity import canonical_json_bytes
from aide.domain.states import AttemptOutcome, DispatchState, TaskState
from aide.orchestration.worker import RecoveryClaim
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    RecoveryEventModel,
    TaskAttemptModel,
)

ReconcileValue = EffectFound | NoEffect | InProgress | Unknown
OutputValidator = Callable[[dict[str, Any]], dict[str, Any]]


async def apply_reconcile_result(
    session: AsyncSession,
    *,
    claim: RecoveryClaim,
    result: ReconcileValue,
    now: datetime,
    max_reconcile_checks: int,
    recovery_lease_duration: timedelta,
    output_validator: OutputValidator | None = None,
) -> TaskState:
    """Apply one connector result under fenced recovery ownership."""
    task = await session.scalar(
        select(MaterializedTaskModel)
        .where(
            MaterializedTaskModel.task_id == claim.task_id,
            MaterializedTaskModel.status == TaskState.RECONCILING.value,
            MaterializedTaskModel.recovery_owner == claim.owner,
            MaterializedTaskModel.claim_epoch == claim.claim_epoch,
            MaterializedTaskModel.active_attempt_id == claim.attempt_id,
        )
        .with_for_update()
    )
    if task is None:
        raise RuntimeError("stale recovery result rejected")
    attempt = await session.get(TaskAttemptModel, claim.attempt_id, with_for_update=True)
    if attempt is None:
        raise LookupError("recovery attempt does not exist")
    task.reconcile_check_count += 1
    evidence = result.model_dump(mode="json")
    session.add(
        RecoveryEventModel(
            task_id=task.task_id,
            attempt_id=attempt.attempt_id,
            recovery_owner=claim.owner,
            claim_epoch=claim.claim_epoch,
            check_number=task.reconcile_check_count,
            result_kind=result.kind,
            evidence=evidence,
        )
    )

    if isinstance(result, EffectFound):
        output = output_validator(result.output) if output_validator is not None else result.output
        digest = hashlib.sha256(canonical_json_bytes(output)).hexdigest()
        task.outputs = output
        task.output_digest = digest
        task.execution_result = {"recovered": True, "external_ref": result.external_ref}
        task.status = TaskState.SUCCEEDED.value
        task.finished_at = now
        attempt.result = output
        attempt.output_digest = digest
        attempt.external_ref = result.external_ref
        attempt.outcome = AttemptOutcome.RECOVERED.value
        attempt.finished_at = now
        await _clear_recovery(task)
        event_type = "TASK_RECOVERED"
    elif isinstance(result, NoEffect):
        attempt.dispatch_state = DispatchState.REJECTED_NO_EFFECT.value
        attempt.outcome = AttemptOutcome.FAILED.value
        attempt.finished_at = now
        if task.attempt_count < task.max_attempts:
            task.status = TaskState.RETRY_WAIT.value
            task.retry_not_before = now
            event_type = "RECOVERY_NO_EFFECT_RETRY"
        else:
            task.status = TaskState.FAILED.value
            task.failure_classification = "AMBIGUOUS_OUTCOME"
            task.disposition_reason = "NO_EFFECT_ATTEMPTS_EXHAUSTED"
            task.finished_at = now
            event_type = "RECOVERY_NO_EFFECT_EXHAUSTED"
        await _clear_recovery(task)
    elif isinstance(result, InProgress):
        exhausted = (
            task.reconcile_check_count >= max_reconcile_checks
            or task.reconcile_deadline is None
            or now >= task.reconcile_deadline
        )
        if exhausted:
            await _park_ambiguous(task, attempt, now, "IN_PROGRESS_EXHAUSTED")
            event_type = "RECOVERY_IN_PROGRESS_EXHAUSTED"
        else:
            attempt.external_ref = result.external_ref
            task.recovery_lease_expires_at = now + recovery_lease_duration
            event_type = "RECOVERY_IN_PROGRESS"
    else:
        await _park_ambiguous(task, attempt, now, "UNKNOWN")
        event_type = "RECOVERY_UNKNOWN"

    await append_audit_event(
        session,
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        operation_idempotency_key=task.operation_idempotency_key,
        event_type=event_type,
        payload={
            "result_kind": result.kind,
            "check_number": task.reconcile_check_count,
        },
    )
    await session.flush()
    return TaskState(task.status)


async def _park_ambiguous(
    task: MaterializedTaskModel,
    attempt: TaskAttemptModel,
    now: datetime,
    reason: str,
) -> None:
    task.status = TaskState.PARKED.value
    task.failure_classification = "AMBIGUOUS_OUTCOME"
    task.disposition_reason = reason
    task.finished_at = now
    attempt.outcome = AttemptOutcome.AMBIGUOUS.value
    attempt.finished_at = now
    await _clear_recovery(task)


async def _clear_recovery(task: MaterializedTaskModel) -> None:
    task.active_attempt_id = None
    task.recovery_owner = None
    task.recovery_lease_expires_at = None
    task.lease_owner = None
    task.lease_expires_at = None
