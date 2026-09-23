"""Server-rendered operator console. No browser storage and no client SQL."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader, select_autoescape

from aide.api.console_ports import ConsoleExport, ConsolePort, ConsoleSession
from aide.app.benchmarking.errors import DemoBusyError
from aide.auth.csrf import CsrfValidationError
from aide.auth.session import (
    SESSION_COOKIE,
    SessionExpiredError,
    SessionInvalidError,
    SessionMissingError,
)
from aide.domain.benchmark import (
    INTERVIEW_REQUEST,
    INTERVIEW_SCENARIO_ID,
    OPERATOR_BUSINESS_CORRECTNESS,
    OPERATOR_EXECUTION_LABEL,
    OPERATOR_LIMITATIONS,
)
from aide.domain.principal import Role

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_LOGIN_COOKIE = "aide_login_nonce"
_MAX_FORM_BYTES = 4096
_CSP = (
    "default-src 'self'; script-src 'none'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'; style-src 'unsafe-inline'"
)


def register_operator_console(
    app: FastAPI,
    *,
    sessions: ConsoleSession,
    console: ConsolePort,
    secure_cookie: bool,
) -> None:
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATES),
        autoescape=select_autoescape(["html", "xml"]),
    )

    def render(name: str, status_code: int = 200, **context: object) -> HTMLResponse:
        body = environment.get_template(name).render(**context)
        response = HTMLResponse(body, status_code=status_code)
        _secure_headers(response)
        return response

    def login_page(status_code: int, error: str) -> HTMLResponse:
        token = secrets.token_urlsafe(24)
        response = render(
            "login.html",
            status_code=status_code,
            configured=console.password_configured(),
            login_token=_login_token(token, sessions.csrf_secret),
            error=error,
        )
        _set_cookie(
            response,
            _LOGIN_COOKIE,
            token,
            secure=secure_cookie,
            path="/console",
            max_age=600,
        )
        return response

    @app.get("/console/login")
    async def login_form(request: Request) -> Response:
        existing = await _optional_operator(sessions, request)
        if existing is not None:
            return _redirect("/console")
        return login_page(200, "")

    @app.post("/console/login")
    async def login_submit(request: Request) -> Response:
        form = await _form_fields(request)
        if not _login_token_ok(
            request.cookies.get(_LOGIN_COOKIE),
            form.get("login_token"),
            sessions.csrf_secret,
        ):
            return login_page(403, "The sign-in form expired. Refresh and try again.")
        if not console.password_configured():
            return login_page(503, "Operator authentication is not configured.")
        if not console.password_matches(form.get("password", "")):
            return login_page(401, "The password was not accepted.")
        issued = await console.issue_operator_session()
        response = _redirect("/console")
        _set_cookie(
            response,
            SESSION_COOKIE,
            issued.opaque_token,
            secure=secure_cookie,
            path="/",
            max_age=8 * 3600,
        )
        response.delete_cookie(_LOGIN_COOKIE, path="/console")
        return response

    @app.post("/console/logout")
    async def logout(request: Request) -> Response:
        try:
            await _mutate(sessions, request)
        except _AuthDenied as exc:
            return render("denied.html", status_code=exc.status_code, detail=exc.detail)
        await sessions.revoke(request.cookies.get(SESSION_COOKIE))
        response = _redirect("/console/login")
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/console")
    async def home(request: Request) -> Response:
        context = await _optional_operator(sessions, request)
        if context is None:
            return _redirect("/console/login")
        csrf = await sessions.csrf_token_for(request.cookies.get(SESSION_COOKIE))
        return render(
            "home.html",
            scenario_id=INTERVIEW_SCENARIO_ID,
            business_objective=INTERVIEW_REQUEST,
            execution_label=OPERATOR_EXECUTION_LABEL,
            business_correctness=OPERATOR_BUSINESS_CORRECTNESS,
            limitations=OPERATOR_LIMITATIONS,
            sources=console.source_catalog(),
            runs=await console.list_runs(),
            csrf_token=csrf,
        )

    @app.post("/console/runs")
    async def start_run(request: Request) -> Response:
        try:
            context = await _mutate(sessions, request)
        except _AuthDenied as exc:
            return render("denied.html", status_code=exc.status_code, detail=exc.detail)
        try:
            run_id = await console.start_run(context.principal_id)
        except DemoBusyError:
            return render(
                "denied.html",
                status_code=409,
                detail=(
                    "A scenario run is already in progress. This request did not start another one."
                ),
            )
        return _redirect(f"/console/runs/{run_id}")

    @app.get("/console/runs/{run_id}")
    async def show_run(request: Request, run_id: UUID) -> Response:
        context = await _optional_operator(sessions, request)
        if context is None:
            return _redirect("/console/login")
        page = await console.run_page(run_id)
        if page is None:
            return render("denied.html", status_code=404, detail="This run is unavailable.")
        return render("run.html", page=page)

    @app.get("/console/runs/{run_id}/exports/{export_name}")
    async def export_run(request: Request, run_id: UUID, export_name: str) -> Response:
        context = await _optional_operator(sessions, request)
        if context is None:
            return render("denied.html", status_code=401, detail="Sign in to export evidence.")
        exported: ConsoleExport | None = await console.export(run_id, export_name)
        if exported is None:
            missing = Response(content="unavailable\n", status_code=404, media_type="text/plain")
            _secure_headers(missing)
            return missing
        response = Response(content=exported.body, media_type=exported.media_type)
        response.headers["Content-Disposition"] = f'attachment; filename="{exported.filename}"'
        _secure_headers(response)
        return response


class _AuthDenied(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def _optional_operator(sessions: ConsoleSession, request: Request) -> _Actor | None:
    try:
        _session, context = await sessions.open_session(request.cookies.get(SESSION_COOKIE))
    except (SessionMissingError, SessionInvalidError, SessionExpiredError):
        return None
    if Role.OPERATOR not in context.principal.roles:
        return None
    return _Actor(context.principal.principal_id)


async def _mutate(sessions: ConsoleSession, request: Request) -> _Actor:
    form = await _form_fields(request)
    try:
        context = await sessions.authenticate(
            request.cookies.get(SESSION_COOKIE),
            csrf_token=form.get("csrf_token"),
            method="POST",
        )
    except SessionMissingError as exc:
        raise _AuthDenied(401, "Sign in to run the scenario.") from exc
    except (SessionInvalidError, SessionExpiredError) as exc:
        raise _AuthDenied(401, "The session is not valid.") from exc
    except CsrfValidationError as exc:
        raise _AuthDenied(403, "The form token was missing or did not match the session.") from exc
    if Role.OPERATOR not in context.principal.roles:
        raise _AuthDenied(403, "An operator session is required.")
    return _Actor(context.principal.principal_id)


class _Actor:
    def __init__(self, principal_id: UUID) -> None:
        self.principal_id = principal_id


async def _form_fields(request: Request) -> dict[str, str]:
    raw = await request.body()
    if len(raw) > _MAX_FORM_BYTES:
        return {}
    parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items() if values}


def _login_token(nonce: str, secret: bytes) -> str:
    return hmac.new(secret, nonce.encode("utf-8"), hashlib.sha256).hexdigest()


def _login_token_ok(nonce: str | None, provided: str | None, secret: bytes) -> bool:
    if not nonce or not provided:
        return False
    expected = _login_token(nonce, secret)
    return hmac.compare_digest(expected, provided)


def _redirect(url: str) -> RedirectResponse:
    response = RedirectResponse(url=url, status_code=303)
    _secure_headers(response)
    return response


def _set_cookie(
    response: Response,
    name: str,
    value: str,
    *,
    secure: bool,
    path: str,
    max_age: int,
) -> None:
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite="lax",
        secure=secure,
        path=path,
        max_age=max_age,
    )


def _secure_headers(response: Response) -> None:
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
