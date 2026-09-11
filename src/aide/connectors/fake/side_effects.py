"""Deterministic side-effect connector with ambiguous-failure injection."""

from __future__ import annotations

from collections import defaultdict, deque
from enum import Enum
from typing import Any

from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown


class FaultMode(str, Enum):
    TIMEOUT = "TIMEOUT"
    CONNECTION_LOSS = "CONNECTION_LOSS"
    RESPONSE_LOSS = "RESPONSE_LOSS"
    FAILURE_AFTER_EFFECT = "FAILURE_AFTER_EFFECT"
    WORKER_CRASH = "WORKER_CRASH"
    LEASE_EXPIRY = "LEASE_EXPIRY"


class AmbiguousSideEffectError(RuntimeError):
    def __init__(self, mode: FaultMode) -> None:
        super().__init__(f"ambiguous side-effect outcome: {mode.value}")
        self.mode = mode


class FakeSideEffectConnector:
    """A first-class fake that records ordering and applies each operation at most once."""

    def __init__(self) -> None:
        self.effects: dict[str, dict[str, Any]] = {}
        self.effect_counts: defaultdict[str, int] = defaultdict(int)
        self.calls: list[tuple[str, str]] = []
        self._faults: dict[str, deque[tuple[FaultMode, bool]]] = defaultdict(deque)
        self._reconcile_results: dict[str, deque[EffectFound | NoEffect | InProgress | Unknown]] = (
            defaultdict(deque)
        )

    def fail_next(
        self,
        operation_key: str,
        mode: FaultMode,
        *,
        effect_applied: bool,
    ) -> None:
        self._faults[operation_key].append((mode, effect_applied))

    def script_reconcile(
        self,
        operation_key: str,
        *results: EffectFound | NoEffect | InProgress | Unknown,
    ) -> None:
        self._reconcile_results[operation_key].extend(results)

    async def execute(self, payload: dict[str, Any], context: CallContext) -> dict[str, Any]:
        key = context.operation_idempotency_key
        self.calls.append(("execute", key))
        if self._faults[key]:
            mode, effect_applied = self._faults[key].popleft()
            if effect_applied:
                self._apply_once(key, payload)
            raise AmbiguousSideEffectError(mode)
        return self._apply_once(key, payload)

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown:
        key = recovery.operation_idempotency_key
        self.calls.append(("reconcile", key))
        if self._reconcile_results[key]:
            return self._reconcile_results[key].popleft()
        output = self.effects.get(key)
        if output is None:
            return NoEffect(evidence="fake store has no matching operation")
        return EffectFound(output=output, external_ref=f"fake:{key}")

    async def cancel(self, operation_key: str) -> Unknown:
        self.calls.append(("cancel", operation_key))
        return Unknown(reason="fake cancellation requires reconciliation")

    def _apply_once(self, operation_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation_key not in self.effects:
            output = {"applied": True, "value": payload}
            self.effects[operation_key] = output
            self.effect_counts[operation_key] += 1
        return self.effects[operation_key]
