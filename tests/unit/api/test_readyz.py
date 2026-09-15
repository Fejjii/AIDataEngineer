from __future__ import annotations

from fastapi.testclient import TestClient

from aide.api.app import create_app
from aide.app.events import EventBus


class _Service:
    @property
    def events(self) -> EventBus:
        return EventBus()

    async def run_offline(self, requirement_text: str, **kwargs: object) -> object:
        raise NotImplementedError(requirement_text)


class _Ready:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok

    async def ready(self) -> None:
        if not self.ok:
            raise RuntimeError("postgresql+psycopg://aide:hidden@127.0.0.1:5432/aide_dev")


def test_readyz_ok_without_checker() -> None:
    client = TestClient(create_app(_Service()))
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_ok_when_checker_passes() -> None:
    client = TestClient(create_app(_Service(), readiness=_Ready()))
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_does_not_leak_database_errors() -> None:
    client = TestClient(create_app(_Service(), readiness=_Ready(ok=False)))
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "not ready"}
    assert "hidden" not in response.text
    assert "postgresql" not in response.text
