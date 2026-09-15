"""Append-only repair event persistence."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.repair import RepairEventKind
from aide.persistence.models import RepairEventModel


class RepairEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        workflow_id: UUID,
        event_kind: RepairEventKind,
        payload: dict[str, Any],
        task_id: UUID | None = None,
        reason_code: str | None = None,
        evidence_ref_id: UUID | None = None,
        artifact_id: UUID | None = None,
    ) -> RepairEventModel:
        row = RepairEventModel(
            event_id=uuid4(),
            workflow_id=workflow_id,
            task_id=task_id,
            event_kind=event_kind.value,
            reason_code=reason_code,
            evidence_ref_id=evidence_ref_id,
            artifact_id=artifact_id,
            payload=payload,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_workflow(self, workflow_id: UUID) -> tuple[RepairEventModel, ...]:
        rows = (
            await self._session.scalars(
                select(RepairEventModel)
                .where(RepairEventModel.workflow_id == workflow_id)
                .order_by(RepairEventModel.created_at, RepairEventModel.event_id)
            )
        ).all()
        return tuple(rows)

    async def count_kind(self, workflow_id: UUID, kind: RepairEventKind) -> int:
        events = await self.list_for_workflow(workflow_id)
        return sum(1 for item in events if item.event_kind == kind.value)
