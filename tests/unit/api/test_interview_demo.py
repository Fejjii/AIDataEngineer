from __future__ import annotations

from fastapi.testclient import TestClient

from aide.api.app import DEMO_TOKEN_HEADER, create_app
from aide.app.benchmarking.errors import DemoBusyError
from aide.app.events import EventBus
from aide.domain.benchmark import (
    INTERVIEW_SCENARIO_ID,
    DigitalTwinSummary,
    InterviewDemoSummary,
    RepairResultSummary,
    SchemaDriftSummary,
    ValueMetrics,
)


class _Service:
    @property
    def events(self) -> EventBus:
        return EventBus()

    async def run_offline(self, requirement_text: str, **kwargs: object) -> object:
        raise NotImplementedError(requirement_text)


def _metrics() -> ValueMetrics:
    return ValueMetrics(
        relevant_assets_analyzed=1,
        models_generated=1,
        governed_tool_operations=1,
        policy_evaluations=1,
        detected_incidents=1,
        automatic_repairs=1,
        human_interventions=0,
        tests_executed=1,
        quality_checks_executed=1,
        evidence_completeness_pct=100,
        total_workflow_duration_ms=1,
        repair_duration_ms=1,
        estimated_engineering_steps_automated=9,
        estimated_engineering_minutes_automated=690,
    )


def _summary() -> InterviewDemoSummary:
    return InterviewDemoSummary(
        scenario_id=INTERVIEW_SCENARIO_ID,
        workflow_status="VERIFIED",
        workflow_ids=("11111111-1111-1111-1111-111111111111",),
        digital_twin=DigitalTwinSummary(pinned_asset_count=0, selected_assets=()),
        schema_drift=SchemaDriftSummary(
            detected=True,
            failure_class="SCHEMA_MISMATCH",
            mapping="INVOICE_STATUS → STATUS",
            asset="VANTARA_RAW.BILLING.INVOICES",
        ),
        repair=RepairResultSummary(
            applied=True,
            apply_count=1,
            allowed=True,
            artifact_path="models/staging/stg_billing__invoices.sql",
        ),
        verifier_verdict="PASS",
        evidence_completeness_pct=100,
        evidence_complete=True,
        determinism=True,
        benchmark_verdict="PASS",
        benchmark_metrics=_metrics(),
    )


class _Demo:
    def __init__(self, summary: InterviewDemoSummary | None = None) -> None:
        self.calls = 0
        self._summary = summary or _summary()

    async def run_synthetic_demo(self) -> InterviewDemoSummary:
        self.calls += 1
        return self._summary


class _Busy:
    async def run_synthetic_demo(self) -> InterviewDemoSummary:
        raise DemoBusyError("synthetic interview demo is already running")


def test_demo_disabled_returns_404() -> None:
    client = TestClient(create_app(_Service()))
    response = client.post("/v1/interview/demo")
    assert response.status_code == 404


def test_demo_rejects_arbitrary_client_input() -> None:
    client = TestClient(create_app(_Service(), interview_demo=_Demo()))
    response = client.post("/v1/interview/demo", json={"sql": "SELECT 1", "requirement": "x"})
    assert response.status_code == 400
    assert "does not accept client input" in response.json()["detail"]
    assert "SELECT" not in response.text


def test_demo_returns_bounded_summary() -> None:
    demo = _Demo()
    client = TestClient(create_app(_Service(), interview_demo=demo))
    response = client.post("/v1/interview/demo", json={})
    assert response.status_code == 200
    body = response.json()
    assert demo.calls == 1
    assert body["scenario_id"] == INTERVIEW_SCENARIO_ID
    assert body["repair"]["apply_count"] == 1
    assert body["verifier_verdict"] == "PASS"
    assert body["benchmark_metrics"]["human_interventions"] == 0
    assert "AIDE_CSRF_SECRET" not in response.text
    assert "SNOWFLAKE" not in response.text
    assert "POSTGRES_PASSWORD" not in response.text


def test_demo_token_is_required_when_configured() -> None:
    client = TestClient(create_app(_Service(), interview_demo=_Demo(), demo_token="gate"))
    denied = client.post("/v1/interview/demo")
    assert denied.status_code == 401
    allowed = client.post("/v1/interview/demo", headers={DEMO_TOKEN_HEADER: "gate"})
    assert allowed.status_code == 200
    assert "gate" not in allowed.text


def test_demo_busy_returns_409() -> None:
    client = TestClient(create_app(_Service(), interview_demo=_Busy()))
    response = client.post("/v1/interview/demo")
    assert response.status_code == 409
