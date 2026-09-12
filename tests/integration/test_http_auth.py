from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.api.app import create_app
from aide.app.events import EventBus
from aide.app.runtime import build_offline_stack
from aide.app.sessions import LocalSessionService
from aide.auth.session import CSRF_HEADER, SESSION_COOKIE, digest_session_token
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import PrincipalRef
from aide.domain.states import WorkflowState
from aide.persistence.repositories import SessionRepository

_HMAC_KEY = b"local-mvp-csrf"
_REQUEST = "Investigate recent order amounts by customer"


class _RecordingSlice:
    def __init__(self) -> None:
        self.events = EventBus()
        self.principal: PrincipalRef | None = None
        self.persist_bootstrap_session: bool | None = None
        self.workflow_id = uuid4()

    async def run_offline(
        self,
        requirement_text: str,
        *,
        requested_grants: frozenset[PermissionLevel] | None = None,
        principal: PrincipalRef | None = None,
        persist_bootstrap_session: bool = True,
    ) -> Any:
        del requirement_text, requested_grants
        self.principal = principal
        self.persist_bootstrap_session = persist_bootstrap_session
        return SimpleNamespace(
            workflow_id=self.workflow_id,
            workflow_state=WorkflowState.COMPLETED.value,
            parked=False,
            principal=principal,
        )


def _cookie(response: Response) -> str:
    value = response.cookies.get(SESSION_COOKIE)
    assert value is not None
    return value


def _app(
    session_factory: async_sessionmaker[AsyncSession],
    service: Any,
) -> tuple[FastAPI, LocalSessionService]:
    sessions = LocalSessionService(session_factory, csrf_secret=_HMAC_KEY)
    return create_app(service, sessions=sessions), sessions


@pytest.mark.asyncio
async def test_session_creation_issues_opaque_non_constant_cookie(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _ = _app(session_factory, _RecordingSlice())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/v1/sessions")
        second = await client.post("/v1/sessions")
    assert first.status_code == 200
    assert second.status_code == 200
    first_cookie = _cookie(first)
    second_cookie = _cookie(second)
    assert first_cookie != "session"
    assert second_cookie != "session"
    assert first_cookie != second_cookie
    assert first.json()["csrf_token"] != second.json()["csrf_token"]
    async with session_factory() as session:
        stored = await SessionRepository(session).get_by_token_digest(
            digest_session_token(first_cookie)
        )
    assert stored is not None
    assert stored.opaque_token_digest != first_cookie
    assert stored.csrf_token_digest == digest_session_token(first.json()["csrf_token"])


@pytest.mark.asyncio
async def test_unauthenticated_workflow_request_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _ = _app(session_factory, _RecordingSlice())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/v1/workflows", json={"requirement": _REQUEST})
    assert response.status_code == 401
    assert response.json()["detail"] == "unauthenticated"


@pytest.mark.asyncio
async def test_invalid_session_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _ = _app(session_factory, _RecordingSlice())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST},
            cookies={SESSION_COOKIE: "not-a-server-session"},
            headers={CSRF_HEADER: "not-a-csrf-token"},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid session"


@pytest.mark.asyncio
async def test_expired_session_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = _RecordingSlice()
    app, sessions = _app(session_factory, recorder)
    issued = await sessions.issue(
        expires_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST},
            cookies={SESSION_COOKIE: issued.opaque_token},
            headers={CSRF_HEADER: issued.csrf_token},
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "session expired"
    assert recorder.principal is None


@pytest.mark.asyncio
async def test_missing_csrf_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _ = _app(session_factory, _RecordingSlice())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/v1/sessions")
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST},
            cookies={SESSION_COOKIE: _cookie(login)},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "csrf required"


@pytest.mark.asyncio
async def test_invalid_csrf_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _ = _app(session_factory, _RecordingSlice())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/v1/sessions")
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST},
            cookies={SESSION_COOKIE: _cookie(login)},
            headers={CSRF_HEADER: "invalid-csrf-value"},
        )
    assert response.status_code == 403
    assert response.json()["detail"] == "invalid csrf"


@pytest.mark.asyncio
async def test_client_supplied_effective_grants_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = _RecordingSlice()
    app, _ = _app(session_factory, recorder)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/v1/sessions")
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST, "effective_grants": ["READ"]},
            cookies={SESSION_COOKIE: _cookie(login)},
            headers={CSRF_HEADER: login.json()["csrf_token"]},
        )
    assert response.status_code == 400
    assert recorder.principal is None


@pytest.mark.asyncio
async def test_client_supplied_principal_fields_are_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = _RecordingSlice()
    app, _ = _app(session_factory, recorder)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/v1/sessions")
        response = await client.post(
            "/v1/workflows",
            json={
                "requirement": _REQUEST,
                "principal_id": str(uuid4()),
                "roles": ["OPERATOR"],
                "authentication_source": "LOCAL_SESSION",
            },
            cookies={SESSION_COOKIE: _cookie(login)},
            headers={CSRF_HEADER: login.json()["csrf_token"]},
        )
    assert response.status_code == 422
    assert recorder.principal is None


@pytest.mark.asyncio
async def test_valid_authenticated_workflow_uses_server_principal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    recorder = _RecordingSlice()
    app, _ = _app(session_factory, recorder)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/v1/sessions")
        cookie = _cookie(login)
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST, "requested_grants": ["READ"]},
            cookies={SESSION_COOKIE: cookie},
            headers={CSRF_HEADER: login.json()["csrf_token"]},
        )
    assert response.status_code == 200
    body = response.json()
    async with session_factory() as session:
        stored = await SessionRepository(session).get_by_token_digest(digest_session_token(cookie))
    assert stored is not None
    assert recorder.principal is not None
    assert recorder.persist_bootstrap_session is False
    assert recorder.principal.principal_id == stored.principal_id
    assert recorder.principal.session_id == stored.session_id
    assert recorder.principal.authentication_source == "LOCAL_SESSION"
    assert body["principal_id"] == str(stored.principal_id)
    assert body["session_id"] == str(stored.session_id)
    assert UUID(body["workflow_id"]) == recorder.workflow_id


@pytest.mark.asyncio
async def test_valid_authenticated_offline_workflow_completes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = build_offline_stack(session_factory)
    app, _ = _app(session_factory, service)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post("/v1/sessions")
        cookie = _cookie(login)
        response = await client.post(
            "/v1/workflows",
            json={"requirement": _REQUEST, "requested_grants": ["READ"]},
            cookies={SESSION_COOKIE: cookie},
            headers={CSRF_HEADER: login.json()["csrf_token"]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == WorkflowState.COMPLETED.value
    assert body["parked"] is False
    async with session_factory() as session:
        stored = await SessionRepository(session).get_by_token_digest(digest_session_token(cookie))
    assert stored is not None
    assert body["principal_id"] == str(stored.principal_id)
    assert body["session_id"] == str(stored.session_id)
