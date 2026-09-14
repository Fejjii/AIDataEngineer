"""Persistence for governed tool-gateway dispatch intents."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.persistence.models import GatewayDispatchIntentModel


class GatewayDispatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        workflow_id: UUID,
        phase_run_id: UUID,
        task_id: UUID,
        attempt_id: UUID,
        action: str,
        capability_id: str,
        connector_id: str | None,
        connector_version: str | None,
        operation_idempotency_key: str,
        resolved_input_digest: str,
        policy_decision: dict[str, Any],
        risk_decision: dict[str, Any],
        approval_id: UUID | None = None,
        status: str = "RECORDED",
    ) -> GatewayDispatchIntentModel:
        row = GatewayDispatchIntentModel(
            intent_id=uuid4(),
            workflow_id=workflow_id,
            phase_run_id=phase_run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            action=action,
            capability_id=capability_id,
            connector_id=connector_id,
            connector_version=connector_version,
            operation_idempotency_key=operation_idempotency_key,
            resolved_input_digest=resolved_input_digest,
            policy_decision=policy_decision,
            risk_decision=risk_decision,
            approval_id=approval_id,
            status=status,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, intent_id: UUID) -> GatewayDispatchIntentModel | None:
        return await self._session.get(GatewayDispatchIntentModel, intent_id)

    async def get_by_attempt(
        self, attempt_id: UUID, action: str
    ) -> GatewayDispatchIntentModel | None:
        row = await self._session.scalar(
            select(GatewayDispatchIntentModel).where(
                GatewayDispatchIntentModel.attempt_id == attempt_id,
                GatewayDispatchIntentModel.action == action,
            )
        )
        return row if isinstance(row, GatewayDispatchIntentModel) else None

    async def complete(
        self,
        intent_id: UUID,
        *,
        status: str,
        now: datetime,
        evidence_ref_id: UUID | None = None,
        result_digest: str | None = None,
    ) -> GatewayDispatchIntentModel | None:
        row = await self._session.get(GatewayDispatchIntentModel, intent_id)
        if row is None:
            return None
        row.status = status
        row.completed_at = now
        if evidence_ref_id is not None:
            row.evidence_ref_id = evidence_ref_id
        if result_digest is not None:
            row.result_digest = result_digest
        await self._session.flush()
        return row
