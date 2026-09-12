"""Minimal FastAPI surface: session cookie, workflow submit, read-only SSE."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from aide.app.events import EventBus
from aide.auth.grants import GrantForgeryError
from aide.domain.permissions import PermissionLevel


class SliceRunner(Protocol):
    async def run_offline(
        self,
        requirement_text: str,
        *,
        requested_grants: frozenset[PermissionLevel] | None = None,
    ) -> Any: ...

    @property
    def events(self) -> EventBus: ...


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=1, max_length=8000)
    requested_grants: tuple[str, ...] = ("READ",)
    effective_grants: tuple[str, ...] | None = None


def create_app(service: SliceRunner, events: EventBus | None = None) -> FastAPI:
    bus = events or service.events
    app = FastAPI(title="AIDataEngineer", version="0.1.0")

    @app.post("/v1/sessions")
    async def login(response: Response) -> dict[str, str]:
        token = "session"
        response.set_cookie("aide_session", token, httponly=True, samesite="lax")
        return {"status": "ok"}

    @app.post("/v1/workflows")
    async def submit(body: SubmitRequest) -> dict[str, Any]:
        if body.effective_grants is not None:
            raise HTTPException(
                status_code=400,
                detail="client supplied effective grants are not trusted",
            )
        try:
            result = await service.run_offline(
                body.requirement,
                requested_grants=frozenset(PermissionLevel(item) for item in body.requested_grants),
            )
        except GrantForgeryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "workflow_id": str(result.workflow_id),
            "state": result.workflow_state,
            "parked": result.parked,
        }

    @app.get("/v1/workflows/{workflow_id}/events")
    async def stream_events(workflow_id: UUID) -> StreamingResponse:
        async def chunks() -> AsyncIterator[str]:
            async for event in bus.stream(workflow_id):
                data = json.dumps(
                    {
                        "event_type": event.event_type,
                        "payload": event.payload,
                        "created_at": event.created_at.isoformat(),
                    }
                )
                yield f"event: {event.event_type}\ndata: {data}\n\n"

        return StreamingResponse(chunks(), media_type="text/event-stream")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
