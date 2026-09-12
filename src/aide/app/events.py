"""In-process read-only event log for SSE."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SliceEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str
    workflow_id: UUID
    payload: dict[str, Any]
    created_at: datetime


class EventBus:
    def __init__(self) -> None:
        self._events: dict[UUID, list[SliceEvent]] = defaultdict(list)

    def publish(self, workflow_id: UUID, event_type: str, payload: dict[str, Any]) -> SliceEvent:
        event = SliceEvent(
            event_type=event_type,
            workflow_id=workflow_id,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        self._events[workflow_id].append(event)
        return event

    def history(self, workflow_id: UUID) -> tuple[SliceEvent, ...]:
        return tuple(self._events[workflow_id])

    async def stream(self, workflow_id: UUID) -> AsyncIterator[SliceEvent]:
        for event in self.history(workflow_id):
            yield event
