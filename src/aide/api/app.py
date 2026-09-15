"""Minimal FastAPI surface: local session cookie, CSRF, workflow submit, SSE."""

from __future__ import annotations

import hmac
import json
from collections.abc import AsyncIterator
from typing import Any, Protocol
from uuid import UUID

from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from aide.app.benchmarking.errors import DemoBusyError
from aide.app.events import EventBus
from aide.auth.context import (
    ClientForgeryError,
    TrustedAuthenticationContext,
    reject_client_identity,
)
from aide.auth.csrf import CsrfValidationError
from aide.auth.grants import GrantForgeryError
from aide.auth.session import (
    CSRF_HEADER,
    SESSION_COOKIE,
    IssuedLocalSession,
    SessionExpiredError,
    SessionInvalidError,
    SessionMissingError,
)
from aide.domain.benchmark import InterviewDemoSummary
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef

DEMO_TOKEN_HEADER = "X-AIDE-Demo-Token"


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


class SessionGate(Protocol):
    async def issue(self) -> IssuedLocalSession: ...

    async def authenticate(
        self,
        opaque_token: str | None,
        *,
        csrf_token: str | None,
        method: str,
    ) -> TrustedAuthenticationContext: ...


class InterviewDemoRunner(Protocol):
    async def run_synthetic_demo(self) -> InterviewDemoSummary: ...


class ReadinessCheck(Protocol):
    async def ready(self) -> None: ...


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(min_length=1, max_length=8000)
    requested_grants: tuple[str, ...] = ("READ",)
    effective_grants: tuple[str, ...] | None = None


def _demo_token_ok(expected: str | None, provided: str | None) -> bool:
    if expected is None or expected == "":
        return True
    if provided is None:
        return False
    return hmac.compare_digest(expected, provided)


def create_app(
    service: SliceRunner,
    events: EventBus | None = None,
    *,
    sessions: SessionGate | None = None,
    interview_demo: InterviewDemoRunner | None = None,
    readiness: ReadinessCheck | None = None,
    demo_token: str | None = None,
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

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        if readiness is None:
            return {"status": "ok"}
        try:
            await readiness.ready()
        except Exception:
            raise HTTPException(status_code=503, detail="not ready") from None
        return {"status": "ok"}

    @app.post("/v1/interview/demo")
    async def run_interview_demo(
        request: Request,
        x_aide_demo_token: str | None = Header(default=None, alias=DEMO_TOKEN_HEADER),
    ) -> dict[str, Any]:
        if interview_demo is None:
            raise HTTPException(status_code=404, detail="synthetic interview demo is disabled")
        if not _demo_token_ok(demo_token, x_aide_demo_token):
            raise HTTPException(status_code=401, detail="demo token required")
        raw = await request.body()
        if raw.strip():
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail="synthetic demo does not accept client input",
                ) from exc
            if payload != {}:
                raise HTTPException(
                    status_code=400,
                    detail="synthetic demo does not accept client input",
                )
        try:
            summary = await interview_demo.run_synthetic_demo()
        except DemoBusyError as exc:
            raise HTTPException(status_code=409, detail="synthetic interview demo is busy") from exc
        return summary.model_dump(mode="json")

    return app
