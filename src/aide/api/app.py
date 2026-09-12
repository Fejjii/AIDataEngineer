"""Minimal FastAPI surface: local session cookie, CSRF, workflow submit, SSE."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import UUID

from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from aide.app.events import EventBus
from aide.app.sessions import (
    CSRF_HEADER,
    SESSION_COOKIE,
    LocalSessionService,
    SessionInvalidError,
    SessionMissingError,
)
from aide.auth.context import ClientForgeryError, reject_client_identity
from aide.auth.csrf import CsrfValidationError
from aide.auth.grants import GrantForgeryError
from aide.auth.session import SessionExpiredError
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef


class SliceRunner(Protocol):
    async def run_offline(
        self,
        requirement_text: str,
        *,
        requested_grants: frozenset[PermissionLevel] | None = None,
        principal: PrincipalRef | None = None,
        persist_bootstrap_session: bool = True,
    ) -> Any: ...

    @property
    def events(self) -> EventBus: ...


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=1, max_length=8000)
    requested_grants: tuple[str, ...] = ("READ",)
    effective_grants: tuple[str, ...] | None = None


def create_app(
    service: SliceRunner,
    events: EventBus | None = None,
    *,
    sessions: LocalSessionService | None = None,
) -> FastAPI:
    bus = events or service.events
    app = FastAPI(title="AIDataEngineer", version="0.1.0")

    @app.post("/v1/sessions")
    async def login(response: Response) -> dict[str, str]:
        if sessions is None:
            raise HTTPException(status_code=503, detail="session service is unavailable")
        issued = await sessions.issue()
        response.set_cookie(
            SESSION_COOKIE,
            issued.opaque_token,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return {"status": "ok", "csrf_token": issued.csrf_token}

    @app.post("/v1/workflows")
    async def submit(
        request: Request,
        body: SubmitRequest,
        aide_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
        x_csrf_token: str | None = Header(default=None, alias=CSRF_HEADER),
    ) -> dict[str, Any]:
        del request
        if sessions is None:
            raise HTTPException(status_code=503, detail="session service is unavailable")
        try:
            reject_client_identity(body.model_dump(exclude_none=True))
        except ClientForgeryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if body.effective_grants is not None:
            raise HTTPException(
                status_code=400,
                detail="client supplied effective grants are not trusted",
            )
        try:
            context = await sessions.authenticate(
                aide_session,
                csrf_token=x_csrf_token,
                method="POST",
            )
        except SessionMissingError as exc:
            raise HTTPException(status_code=401, detail="unauthenticated") from exc
        except SessionInvalidError as exc:
            raise HTTPException(status_code=401, detail="invalid session") from exc
        except SessionExpiredError as exc:
            raise HTTPException(status_code=401, detail="session expired") from exc
        except CsrfValidationError as exc:
            detail = "csrf required" if not x_csrf_token else "invalid csrf"
            raise HTTPException(status_code=403, detail=detail) from exc
        try:
            result = await service.run_offline(
                body.requirement,
                requested_grants=frozenset(PermissionLevel(item) for item in body.requested_grants),
                principal=context.principal,
                persist_bootstrap_session=False,
            )
        except GrantForgeryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "workflow_id": str(result.workflow_id),
            "state": result.workflow_state,
            "parked": result.parked,
            "principal_id": str(result.principal.principal_id),
            "session_id": str(result.principal.session_id),
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
