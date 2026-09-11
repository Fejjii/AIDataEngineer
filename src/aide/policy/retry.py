"""Canonical max_attempts and evidence-based retry decisions."""

from __future__ import annotations

from enum import Enum

from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.domain.effects import EffectSemantics
from aide.domain.failures import FailureClass
from aide.domain.states import DispatchState


class RetryDecision(str, Enum):
    RETRY = "RETRY"
    RECONCILE_FIRST = "RECONCILE_FIRST"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARK = "PARK"
    WAIT_IN_PROGRESS = "WAIT_IN_PROGRESS"


_AMBIGUOUS_FAILURES = frozenset(
    {
        FailureClass.CONNECTOR_FAILURE,
        FailureClass.TRANSIENT_PROVIDER,
        FailureClass.TIMEOUT,
    }
)


def attempts_remain(attempt_count: int, max_attempts: int) -> bool:
    """``max_attempts`` includes the initial attempt. ``attempt_count`` is created attempts."""
    if max_attempts < 1:
        raise ValueError("max_attempts must include the initial attempt and be >= 1")
    return attempt_count < max_attempts


def decide_after_failure(
    *,
    effect_semantics: EffectSemantics,
    dispatch_state: DispatchState,
    failure_class: FailureClass | None,
    attempt_count: int,
    max_attempts: int,
) -> RetryDecision:
    """Never blindly retry side-effecting CONNECTOR_FAILURE / TRANSIENT / TIMEOUT."""
    if effect_semantics is EffectSemantics.SIDE_EFFECT_FREE:
        if attempts_remain(attempt_count, max_attempts):
            return RetryDecision.RETRY
        return RetryDecision.FAILED

    if dispatch_state is DispatchState.NOT_DISPATCHED:
        if attempts_remain(attempt_count, max_attempts):
            return RetryDecision.RETRY
        return RetryDecision.FAILED

    if dispatch_state is DispatchState.REJECTED_NO_EFFECT:
        if attempts_remain(attempt_count, max_attempts):
            return RetryDecision.RETRY
        return RetryDecision.FAILED

    if dispatch_state is DispatchState.OUTCOME_AMBIGUOUS:
        return RetryDecision.RECONCILE_FIRST

    if failure_class in _AMBIGUOUS_FAILURES:
        return RetryDecision.RECONCILE_FIRST

    return RetryDecision.RECONCILE_FIRST


def decide_after_reconcile(
    result: EffectFound | NoEffect | InProgress | Unknown,
    *,
    attempt_count: int,
    max_attempts: int,
) -> RetryDecision:
    if isinstance(result, EffectFound):
        return RetryDecision.SUCCEEDED
    if isinstance(result, InProgress):
        return RetryDecision.WAIT_IN_PROGRESS
    if isinstance(result, Unknown):
        return RetryDecision.PARK
    if isinstance(result, NoEffect):
        if attempts_remain(attempt_count, max_attempts):
            return RetryDecision.RETRY
        return RetryDecision.FAILED
    raise TypeError(f"unknown reconcile result {type(result)!r}")
