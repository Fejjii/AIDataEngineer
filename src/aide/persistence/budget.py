"""Atomic budget reservation and settlement."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.costs import BudgetScope, CostUnit
from aide.persistence.audit import append_audit_event
from aide.persistence.models import BudgetEntryModel, BudgetLedgerModel


class BudgetExceededError(RuntimeError):
    """Raised before dispatch when a worst-case reservation exceeds the cap."""


class InvalidSettlementError(ValueError):
    pass


@dataclass(frozen=True)
class BudgetReservation:
    reservation_id: UUID
    ledger_id: UUID
    reserved_amount: Decimal
    remaining_budget: Decimal
    ledger_version: int


@dataclass(frozen=True)
class BudgetSettlement:
    reservation_id: UUID
    actual_amount: Decimal
    released_amount: Decimal
    remaining_budget: Decimal
    ledger_version: int


class BudgetLedger:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        workflow_id: UUID,
        scope: BudgetScope,
        unit: CostUnit,
        authorized_cap: Decimal,
    ) -> BudgetLedgerModel:
        row = BudgetLedgerModel(
            workflow_id=workflow_id,
            scope=scope.value,
            unit=unit.value,
            authorized_cap=authorized_cap,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def reserve(
        self,
        *,
        workflow_id: UUID,
        scope: BudgetScope,
        unit: CostUnit,
        worst_case: Decimal,
        evidence: dict[str, Any],
        reservation_id: UUID | None = None,
    ) -> BudgetReservation:
        if worst_case <= 0:
            raise ValueError("worst_case must be positive")
        ledger = await self._locked_ledger(workflow_id, scope, unit)
        remaining = ledger.authorized_cap - ledger.reserved_amount - ledger.settled_amount
        if worst_case > remaining:
            raise BudgetExceededError(
                f"reservation {worst_case} exceeds remaining authorized budget {remaining}"
            )
        resolved_id = reservation_id or uuid4()
        ledger.reserved_amount += worst_case
        ledger.version += 1
        self._session.add(
            BudgetEntryModel(
                ledger_id=ledger.ledger_id,
                reservation_id=resolved_id,
                entry_kind="RESERVE",
                amount=worst_case,
                evidence=evidence,
            )
        )
        await append_audit_event(
            self._session,
            workflow_id=workflow_id,
            event_type="BUDGET_RESERVED",
            payload={
                "reservation_id": str(resolved_id),
                "scope": scope.value,
                "unit": unit.value,
                "amount": str(worst_case),
                "ledger_version": ledger.version,
            },
        )
        await self._session.flush()
        return BudgetReservation(
            reservation_id=resolved_id,
            ledger_id=ledger.ledger_id,
            reserved_amount=worst_case,
            remaining_budget=remaining - worst_case,
            ledger_version=ledger.version,
        )

    async def settle(
        self,
        *,
        workflow_id: UUID,
        scope: BudgetScope,
        unit: CostUnit,
        reservation_id: UUID,
        actual_amount: Decimal,
        evidence: dict[str, Any],
    ) -> BudgetSettlement:
        if actual_amount < 0:
            raise InvalidSettlementError("actual_amount cannot be negative")
        ledger = await self._locked_ledger(workflow_id, scope, unit)
        reserve_entry = await self._session.scalar(
            select(BudgetEntryModel).where(
                BudgetEntryModel.ledger_id == ledger.ledger_id,
                BudgetEntryModel.reservation_id == reservation_id,
                BudgetEntryModel.entry_kind == "RESERVE",
            )
        )
        if reserve_entry is None:
            raise InvalidSettlementError("reservation does not exist")
        settled_entry = await self._session.scalar(
            select(BudgetEntryModel).where(
                BudgetEntryModel.ledger_id == ledger.ledger_id,
                BudgetEntryModel.reservation_id == reservation_id,
                BudgetEntryModel.entry_kind == "SETTLE",
            )
        )
        if settled_entry is not None:
            raise InvalidSettlementError("reservation already settled")
        if actual_amount > reserve_entry.amount:
            raise InvalidSettlementError("actual amount exceeds worst-case reservation")

        released = reserve_entry.amount - actual_amount
        ledger.reserved_amount -= reserve_entry.amount
        ledger.settled_amount += actual_amount
        ledger.version += 1
        self._session.add_all(
            [
                BudgetEntryModel(
                    ledger_id=ledger.ledger_id,
                    reservation_id=reservation_id,
                    entry_kind="SETTLE",
                    amount=actual_amount,
                    evidence=evidence,
                ),
                BudgetEntryModel(
                    ledger_id=ledger.ledger_id,
                    reservation_id=reservation_id,
                    entry_kind="RELEASE",
                    amount=released,
                    evidence={"reason": "unused_reservation"},
                ),
            ]
        )
        await append_audit_event(
            self._session,
            workflow_id=workflow_id,
            event_type="BUDGET_SETTLED",
            payload={
                "reservation_id": str(reservation_id),
                "actual_amount": str(actual_amount),
                "released_amount": str(released),
                "ledger_version": ledger.version,
            },
        )
        await self._session.flush()
        remaining = ledger.authorized_cap - ledger.reserved_amount - ledger.settled_amount
        return BudgetSettlement(
            reservation_id=reservation_id,
            actual_amount=actual_amount,
            released_amount=released,
            remaining_budget=remaining,
            ledger_version=ledger.version,
        )

    async def _locked_ledger(
        self, workflow_id: UUID, scope: BudgetScope, unit: CostUnit
    ) -> BudgetLedgerModel:
        ledger = await self._session.scalar(
            select(BudgetLedgerModel)
            .where(
                BudgetLedgerModel.workflow_id == workflow_id,
                BudgetLedgerModel.scope == scope.value,
                BudgetLedgerModel.unit == unit.value,
            )
            .with_for_update()
        )
        if ledger is None:
            raise LookupError("budget ledger does not exist")
        return ledger
