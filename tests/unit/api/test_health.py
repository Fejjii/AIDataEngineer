from __future__ import annotations

from fastapi.testclient import TestClient

from aide.api.app import create_app
from aide.app.events import EventBus


def test_healthz() -> None:
    class _Service:
        @property
        def events(self) -> EventBus:
            return EventBus()

        async def run_offline(self, requirement_text: str, **kwargs: object) -> object:
            raise NotImplementedError(requirement_text)

    app = create_app(_Service())
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
