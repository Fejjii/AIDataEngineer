"""Container ASGI entrypoint outside the `aide` package import graph."""

from __future__ import annotations

import os

from fastapi import FastAPI

from aide.api.app import create_app
from aide.app.benchmarking.service import SyntheticInterviewDemoService
from aide.app.runtime import DatabaseReadiness, build_offline_stack, session_factory_from_url
from aide.app.sessions import LocalSessionService


def _database_url() -> str:
    url = os.environ.get("AIDE_DATABASE_URL") or os.environ.get("AIDE_TEST_DATABASE_URL")
    if not url:
        msg = "AIDE_DATABASE_URL or AIDE_TEST_DATABASE_URL must be set"
        raise RuntimeError(msg)
    return url


def _csrf_secret() -> bytes:
    raw = os.environ.get("AIDE_CSRF_SECRET", "")
    if len(raw) < 32:
        msg = "AIDE_CSRF_SECRET must be at least 32 characters"
        raise RuntimeError(msg)
    return raw.encode()


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _demo_token() -> str | None:
    raw = os.environ.get("AIDE_SYNTHETIC_DEMO_TOKEN", "").strip()
    return raw or None


def create_production_app() -> FastAPI:
    factory = session_factory_from_url(_database_url())
    service = build_offline_stack(factory)
    sessions = LocalSessionService(factory, csrf_secret=_csrf_secret())
    interview_demo = (
        SyntheticInterviewDemoService(factory) if _flag("AIDE_SYNTHETIC_DEMO_HTTP") else None
    )
    return create_app(
        service,
        sessions=sessions,
        interview_demo=interview_demo,
        readiness=DatabaseReadiness(factory),
        demo_token=_demo_token(),
    )


app = create_production_app()
