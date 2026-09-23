from __future__ import annotations

from fastapi.testclient import TestClient

from aide.api.app import create_app
from aide.app.events import EventBus


class _Service:
    @property
    def events(self) -> EventBus:
        return EventBus()

    async def run_offline(self, requirement_text: str, **kwargs: object) -> object:
        raise AssertionError(requirement_text)


def test_anonymous_legacy_routes_are_not_registered() -> None:
    client = TestClient(create_app(_Service()))
    workflow_id = "11111111-1111-1111-1111-111111111111"
    assert client.post("/v1/sessions").status_code == 404
    assert client.post("/v1/workflows", json={"requirement": "investigate"}).status_code == 404
    assert client.get(f"/v1/workflows/{workflow_id}/events").status_code == 404
