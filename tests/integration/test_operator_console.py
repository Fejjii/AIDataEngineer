from __future__ import annotations

import asyncio
import re
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.api.app import create_app
from aide.app.benchmarking.service import SyntheticInterviewDemoService
from aide.app.console.service import OperatorConsoleService
from aide.app.events import EventBus
from aide.app.sessions import LocalSessionService
from aide.persistence.console import ConsoleRunRepository, console_now
from aide.persistence.models import OperatorConsoleRunModel, SessionModel, WorkflowModel

_PASSWORD = "operator-" + "test-password"
_SECRET = b"0123456789abcdef0123456789abcdef"


class _Slice:
    def __init__(self) -> None:
        self.events = EventBus()

    async def run_offline(self, requirement_text: str, **kwargs: object) -> object:
        raise AssertionError(requirement_text)


class _StubDemo:
    def __init__(self) -> None:
        self._active = False
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def try_begin(self) -> bool:
        if self._active:
            return False
        self._active = True
        return True

    def end(self) -> None:
        self._active = False

    async def execute_benchmark(self) -> tuple[object, object, object]:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        raise RuntimeError("boom <script>alert(1)</script>")


def _body(html: str) -> str:
    """Rendered markup after the inline stylesheet, so CSS selectors do not count."""
    return html.split("<main", 1)[1]


def _hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', html)
    assert match is not None
    return match.group(1)


async def _count(factory: async_sessionmaker[AsyncSession], model: type[object]) -> int:
    async with factory() as db:
        value = await db.scalar(select(func.count()).select_from(model))
    return int(value or 0)


def _app(
    factory: async_sessionmaker[AsyncSession],
    demo: object,
    *,
    secure: bool = False,
) -> tuple[FastAPI, OperatorConsoleService]:
    sessions = LocalSessionService(factory, csrf_secret=_SECRET)
    console = OperatorConsoleService(
        factory,
        sessions=sessions,
        demo=demo,  # type: ignore[arg-type]
        operator_password=_PASSWORD,
    )
    app = create_app(
        _Slice(),
        sessions=sessions,
        console=console,
        secure_session_cookie=secure,
    )
    return app, console


async def _sign_in(client: AsyncClient) -> None:
    page = await client.get("/console/login")
    assert page.status_code == 200
    response = await client.post(
        "/console/login",
        data={"login_token": _hidden(page.text, "login_token"), "password": _PASSWORD},
    )
    assert response.status_code == 303
    assert _PASSWORD not in response.text
    assert "password" not in response.headers.get("location", "")
    cookie = response.headers.get("set-cookie", "")
    assert "httponly" in cookie.lower()
    assert _PASSWORD not in cookie


@pytest.mark.asyncio
async def test_unauthenticated_console_does_not_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _console = _app(session_factory, _StubDemo())
    before_sessions = await _count(session_factory, SessionModel)
    before_runs = await _count(session_factory, OperatorConsoleRunModel)
    before_workflows = await _count(session_factory, WorkflowModel)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        home = await client.get("/console")
        denied = await client.post("/console/runs", data={"csrf_token": "nope"})
        legacy = await client.post("/v1/sessions")
        events = await client.get("/v1/workflows/11111111-1111-1111-1111-111111111111/events")
    assert home.status_code == 303
    assert denied.status_code == 401
    assert legacy.status_code == 404
    assert events.status_code == 404
    assert await _count(session_factory, SessionModel) == before_sessions
    assert await _count(session_factory, OperatorConsoleRunModel) == before_runs
    assert await _count(session_factory, WorkflowModel) == before_workflows


@pytest.mark.asyncio
async def test_wrong_password_and_bad_csrf_do_not_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _console = _app(session_factory, _StubDemo())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/console/login")
        rejected = await client.post(
            "/console/login",
            data={
                "login_token": _hidden(page.text, "login_token"),
                "password": "wrong-password-value",
            },
        )
        assert rejected.status_code == 401
        assert await _count(session_factory, SessionModel) == 0
        await _sign_in(client)
        home = await client.get("/console")
        assert "taylor.johnson7213@novasystems-0.com" not in home.text
        assert "NOT_VALIDATED" in home.text
        assert "Run Data Engineering Workflow" in home.text
        # Run-scoped navigation has no backing data before the first completed run.
        assert "Incident and Repair" not in home.text
        assert "No persisted runs yet" in home.text
        blocked = await client.post("/console/runs", data={})
        assert blocked.status_code == 403
        assert await _count(session_factory, OperatorConsoleRunModel) == 0


@pytest.mark.asyncio
async def test_double_submit_refresh_escape_and_missing_export(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    demo = _StubDemo()
    app, console = _app(session_factory, demo)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _sign_in(client)
        home = await client.get("/console")
        csrf = _hidden(home.text, "csrf_token")
        started = await client.post("/console/runs", data={"csrf_token": csrf})
        assert started.status_code == 303
        await demo.started.wait()
        again = await client.post("/console/runs", data={"csrf_token": csrf})
        assert again.status_code == 409
        assert demo.calls == 1
        run_id = started.headers["location"].rsplit("/", 1)[-1]
        running = await client.get(f"/console/runs/{run_id}")
        assert running.status_code == 200
        assert "Workflow running" in running.text
        assert "Running." in running.text
        assert "does not invent stages" in running.text
        assert 'data-state="complete"' not in _body(running.text)
        home_while_running = await client.get("/console")
        assert "View running workflow" in home_while_running.text
        demo.release.set()
        await console.wait()
        failed = await client.get(f"/console/runs/{run_id}")
        assert failed.status_code == 200
        assert "failed" in failed.text
        assert "<script>alert(1)</script>" not in failed.text
        assert "&lt;script&gt;" in failed.text
        assert 'data-benchmark="unavailable"' in failed.text
        assert 'data-verifier="PASS"' not in failed.text
        refreshed = await client.get(f"/console/runs/{run_id}")
        assert refreshed.status_code == 200
        assert demo.calls == 1
        exported = await client.get(f"/console/runs/{run_id}/exports/../secrets")
        missing = await client.get(f"/console/runs/{run_id}/exports/not-a-real-export")
        assert exported.status_code in {404, 307}
        assert missing.status_code == 404
        assert missing.text.strip() == "unavailable"
    assert await _count(session_factory, OperatorConsoleRunModel) == 1


@pytest.mark.asyncio
async def test_completed_run_without_artifacts_is_not_pass(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    app, _console = _app(session_factory, _StubDemo())
    workflow_id = str(uuid4())
    run_id = uuid4()
    async with session_factory() as db, db.begin():
        await ConsoleRunRepository(db).add(
            run_id=run_id,
            principal_id=uuid4(),
            started_at=console_now(),
        )
        await ConsoleRunRepository(db).complete(
            run_id,
            workflow_ids=[workflow_id],
            snapshot_artifact_id=None,
            finished_at=console_now(),
        )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _sign_in(client)
        page = await client.get(f"/console/runs/{run_id}")
    assert page.status_code == 200
    assert 'data-verifier="unavailable"' in page.text
    assert 'data-verifier="PASS"' not in page.text
    assert 'data-benchmark="unavailable"' in page.text
    assert "NOT_VALIDATED" in page.text


@pytest.mark.asyncio
async def test_restart_marks_running_rows_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _app_obj, console = _app(session_factory, _StubDemo())
    del _app_obj
    run_id = uuid4()
    async with session_factory() as db, db.begin():
        await ConsoleRunRepository(db).add(
            run_id=run_id,
            principal_id=uuid4(),
            started_at=console_now(),
        )
    await console.reconcile_interrupted_runs()
    async with session_factory() as db:
        row = await ConsoleRunRepository(db).get(run_id)
    assert row is not None
    assert row.status == "failed"
    assert row.error_message is not None
    assert "PASS" not in row.error_message
    assert "unavailable" in row.error_message


@pytest.mark.asyncio
async def test_secure_cookie_flag_and_real_scenario(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    demo = SyntheticInterviewDemoService(session_factory)
    app, console = _app(session_factory, demo, secure=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/console/login")
        response = await client.post(
            "/console/login",
            data={"login_token": _hidden(page.text, "login_token"), "password": _PASSWORD},
        )
        assert "secure" in response.headers.get("set-cookie", "").lower()
        # The secure flag is not stored by an HTTP client. Sign in again without it
        # so the rest of this test can use the session on http://test.
    app, console = _app(session_factory, demo, secure=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _sign_in(client)
        home = await client.get("/console")
        started = await client.post(
            "/console/runs",
            data={"csrf_token": _hidden(home.text, "csrf_token")},
        )
        assert started.status_code == 303
        await console.wait()
        run_id = started.headers["location"].rsplit("/", 1)[-1]
        UUID(run_id)
        page = await client.get(f"/console/runs/{run_id}")
        assert page.status_code == 200
        assert "completed" in page.text
        assert "stg_billing__invoices.sql" in page.text
        assert "NOT_VALIDATED" in page.text
        assert "canonical invoice currency" in page.text
        assert "different currencies are not summed" in page.text
        assert page.text.count("Workflow ") >= 2 or page.text.count("workflow") >= 1
        # The engineering loop is populated from persisted evidence only.
        assert _body(page.text).count('data-state="complete"') == 12
        assert 'data-state="unavailable"' not in _body(page.text)
        assert 'data-state="issue"' not in _body(page.text)
        assert 'data-drift="present"' in page.text
        assert "INVOICE_STATUS" in page.text and "SCHEMA_MISMATCH" in page.text
        assert "Independent Evidence Verification" in page.text
        assert "does not independently rerun the warehouse" in page.text
        assert 'data-verifier="PASS"' in page.text
        assert 'data-preview="present"' in page.text
        assert 'data-metric="human"' in page.text
        preview = await client.get(f"/console/runs/{run_id}/exports/output-preview")
        assert preview.status_code == 200
        assert "invoiced_amount" in preview.text
        assert "text/csv" in preview.headers["content-type"]
        for name in ("verifier", "tests", "quality", "generated-sql", "repaired-sql"):
            exported = await client.get(f"/console/runs/{run_id}/exports/{name}")
            assert exported.status_code == 200, name
        again = await client.get(f"/console/runs/{run_id}")
        assert again.status_code == 200
        home = await client.get("/console")
        assert "Incident and Repair" in home.text
        assert f"/console/runs/{run_id}#incident" in home.text
        assert "No persisted runs yet" not in home.text
    async with session_factory() as db:
        row = await ConsoleRunRepository(db).get(UUID(run_id))
    assert row is not None
    assert row.status == "completed"
    assert len(row.workflow_ids) == 2
