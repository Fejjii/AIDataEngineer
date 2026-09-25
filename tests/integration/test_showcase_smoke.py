"""Operator-console smoke for the recruiter Interview MVP story.

Exercises the FastAPI console and the real synthetic benchmark. Assertions
read persisted artifacts and the typed run page. Metric counts are taken from
those records. Verifier PASS is not treated as business correctness.
"""

from __future__ import annotations

import re
import sys
from uuid import UUID

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.evaluation.showcase_summary import format_showcase_summary, summary_from_run_page

from aide.api.app import create_app
from aide.app.benchmarking.service import SyntheticInterviewDemoService
from aide.app.console.present import RunPage
from aide.app.console.service import OperatorConsoleService
from aide.app.events import EventBus
from aide.app.sessions import LocalSessionService
from aide.domain.benchmark import OPERATOR_BUSINESS_CORRECTNESS
from aide.domain.repair import (
    ACCEPTED_ARTIFACT_PATH,
    ACCEPTED_FROM_COLUMN,
    ACCEPTED_TO_COLUMN,
)
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS
from aide.persistence.console import ConsoleRunRepository
from aide.persistence.models import OperatorConsoleRunModel, WorkflowModel

_PASSWORD = "operator-" + "showcase-password"
_SECRET = b"0123456789abcdef0123456789abcdef"
_LEGACY_WORKFLOW = "11111111-1111-1111-1111-111111111111"

_WORKFLOW_ARTIFACTS = (
    "twin_snapshot",
    "estate_context",
    "dbt_parse",
    "dbt_compile",
    "dbt_execution",
    "dbt_tests",
    "quality_results",
    "twin_observations",
    "repair_proposal",
    "repair_validation",
    "repair_application",
    "post_repair_validation",
    "verifier_verdict",
    "evidence_bundle",
)


class _Slice:
    def __init__(self) -> None:
        self.events = EventBus()

    async def run_offline(self, requirement_text: str, **kwargs: object) -> object:
        raise AssertionError(requirement_text)


def _hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', html)
    assert match is not None
    return match.group(1)


def _app(
    factory: async_sessionmaker[AsyncSession],
    demo: SyntheticInterviewDemoService,
) -> tuple[FastAPI, OperatorConsoleService]:
    sessions = LocalSessionService(factory, csrf_secret=_SECRET)
    console = OperatorConsoleService(
        factory,
        sessions=sessions,
        demo=demo,
        operator_password=_PASSWORD,
    )
    app = create_app(_Slice(), sessions=sessions, console=console)
    return app, console


async def _count(factory: async_sessionmaker[AsyncSession], model: type[object]) -> int:
    async with factory() as db:
        value = await db.scalar(select(func.count()).select_from(model))
    return int(value or 0)


async def _sign_in(client: AsyncClient) -> None:
    page = await client.get("/console/login")
    assert page.status_code == 200
    response = await client.post(
        "/console/login",
        data={"login_token": _hidden(page.text, "login_token"), "password": _PASSWORD},
    )
    assert response.status_code == 303
    assert "httponly" in response.headers.get("set-cookie", "").lower()
    assert _PASSWORD not in response.headers.get("set-cookie", "")


def _body(
    artifacts: dict[str, dict[str, dict[str, object]]], workflow_id: str, name: str
) -> dict[str, object]:
    raw = artifacts.get(workflow_id, {}).get(name)
    assert isinstance(raw, dict), f"{name} missing for {workflow_id}"
    return raw


def _flag(body: dict[str, object], key: str) -> bool:
    assert key in body, key
    assert body[key] is True, key
    return True


@pytest.mark.asyncio
async def test_showcase_smoke_operator_story(
    session_factory: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    demo = SyntheticInterviewDemoService(session_factory)
    app, console = _app(session_factory, demo)
    catalog = console.source_catalog()
    assert catalog.tables
    assert catalog.database
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        home = await anon.get("/console")
        assert home.status_code == 303
        denied = await anon.post("/console/runs", data={"csrf_token": "nope"})
        assert denied.status_code == 401
        legacy_session = await anon.post("/v1/sessions")
        legacy_workflow = await anon.post("/v1/workflows", json={"requirement": "investigate"})
        legacy_events = await anon.get(f"/v1/workflows/{_LEGACY_WORKFLOW}/events")
        assert legacy_session.status_code == 404
        assert legacy_workflow.status_code == 404
        assert legacy_events.status_code == 404

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await _sign_in(client)
        home = await client.get("/console")
        assert home.status_code == 200
        assert catalog.database in home.text
        for table in catalog.tables:
            assert table.name in home.text
            assert table.schema in home.text
            for column in table.columns:
                assert column.name in home.text
                assert column.data_type in home.text
        assert "VALIDATED_SYNTHETIC_CONTRACT" in home.text
        runs_before = await _count(session_factory, OperatorConsoleRunModel)
        workflows_before = await _count(session_factory, WorkflowModel)
        started = await client.post(
            "/console/runs",
            data={"csrf_token": _hidden(home.text, "csrf_token")},
        )
        assert started.status_code == 303
        run_id = UUID(started.headers["location"].rsplit("/", 1)[-1])
        assert await _count(session_factory, OperatorConsoleRunModel) == runs_before + 1
        await console.wait()
        page = await client.get(f"/console/runs/{run_id}")
        assert page.status_code == 200
        run_page = await console.run_page(run_id)
        assert run_page is not None
        summary = summary_from_run_page(run_page)
        rendered = format_showcase_summary(summary)
        print(rendered)
        artifacts = await _artifacts(session_factory, run_id)
        _assert_persisted_story(run_page, summary.verifier, artifacts)
        assert summary.business_correctness == OPERATOR_BUSINESS_CORRECTNESS
        assert summary.business_correctness != "PASS"
        assert summary.verifier != summary.business_correctness
        assert f'data-verifier="{summary.verifier}"' in page.text
        assert "VALIDATED_SYNTHETIC_CONTRACT" in page.text
        exported = await client.get(f"/console/runs/{run_id}/exports/generated-sql")
        assert exported.status_code == 200
        assert run_page.primary is not None
        assert run_page.primary.models[0].path in exported.text
        assert run_page.primary.models[0].sql.splitlines()[0] in exported.text
        runs_after = await _count(session_factory, OperatorConsoleRunModel)
        workflows_after = await _count(session_factory, WorkflowModel)
        reopened = await client.get(f"/console/runs/{run_id}")
        history = await client.get("/console")
        assert reopened.status_code == 200
        assert f"/console/runs/{run_id}" in history.text
        assert await _count(session_factory, OperatorConsoleRunModel) == runs_after
        assert await _count(session_factory, WorkflowModel) == workflows_after
        assert runs_after == runs_before + 1
        assert workflows_after > workflows_before
    captured = capsys.readouterr()
    assert "business correctness: VALIDATED_SYNTHETIC_CONTRACT" in captured.out
    assert "business correctness: PASS" not in captured.out
    stdout = sys.__stdout__
    if stdout is not None:
        stdout.write(captured.out)


async def _artifacts(
    factory: async_sessionmaker[AsyncSession], run_id: UUID
) -> dict[str, dict[str, dict[str, object]]]:
    async with factory() as db:
        row = await ConsoleRunRepository(db).get(run_id)
        assert row is not None
        assert row.status == "completed"
        identifiers = tuple(UUID(str(item)) for item in row.workflow_ids)
        found = await ConsoleRunRepository(db).allowlisted_artifacts(identifiers)
    return {str(key): value for key, value in found.items()}


def _assert_persisted_story(
    page: RunPage,
    summary_verifier: str,
    artifacts: dict[str, dict[str, dict[str, object]]],
) -> None:
    assert page.status == "completed"
    assert page.workflow_outcome == "VERIFIED"
    assert page.benchmark_verdict == "PASS"
    assert page.business_correctness == OPERATOR_BUSINESS_CORRECTNESS
    assert page.determinism == "true"
    assert page.evidence_complete == "true"
    assert len(page.workflows) == 2
    snapshot = _snapshot(artifacts, page.workflows[0].workflow_id)
    completeness = snapshot["evidence_completeness"]
    assert isinstance(completeness, dict)
    required = completeness["required_sections"]
    missing = completeness["missing_sections"]
    assert isinstance(required, list) and required
    assert missing == []
    present_required = len(required) - len(missing)
    expected_pct = int((present_required * 100) / len(required))
    assert completeness["completeness_pct"] == expected_pct
    assert completeness["complete"] is True
    assert snapshot["determinism_equivalent"] is True
    assert snapshot["business_correctness"] == OPERATOR_BUSINESS_CORRECTNESS
    model_paths: list[tuple[str, ...]] = []
    verdicts: list[str] = []
    for panel in page.workflows:
        bodies = artifacts[panel.workflow_id]
        for name in _WORKFLOW_ARTIFACTS:
            assert name in bodies, name
        twin = _body(artifacts, panel.workflow_id, "twin_snapshot")
        assert isinstance(twin.get("twin_snapshot_id"), str) and twin["twin_snapshot_id"]
        assert panel.twin.state == "present"
        assert panel.twin.snapshot_id == twin["twin_snapshot_id"]
        estate = _body(artifacts, panel.workflow_id, "estate_context")
        assert isinstance(estate.get("sha256"), str) and len(str(estate["sha256"])) == 64
        workflow_snapshot = _workflow_snapshot(snapshot, panel.workflow_id)
        models = workflow_snapshot["models"]
        assert isinstance(models, list) and models
        paths: list[str] = []
        for item in models:
            assert isinstance(item, dict)
            assert isinstance(item.get("path"), str) and str(item["path"]).startswith("models/")
            assert isinstance(item.get("sql"), str) and item["sql"].strip()
            paths.append(str(item["path"]))
        model_paths.append(tuple(paths))
        assert ACCEPTED_ARTIFACT_PATH in paths
        for key in ("dbt_parse", "dbt_compile", "dbt_execution", "dbt_tests"):
            _flag(_body(artifacts, panel.workflow_id, key), "ok")
        execution = _body(artifacts, panel.workflow_id, "dbt_execution")
        results = execution.get("results")
        if isinstance(results, list) and results:
            assert all(
                isinstance(item, dict) and item.get("status") == "success" for item in results
            )
        tests = workflow_snapshot["individual_tests"]
        assert isinstance(tests, list) and tests
        assert all(isinstance(item, dict) and item.get("status") == "pass" for item in tests)
        assert workflow_snapshot["tests_executed"] == len(tests)
        assert panel.quality.tests_state == "present"
        assert panel.quality.tests_passed == panel.quality.tests_total
        quality = _body(artifacts, panel.workflow_id, "quality_results")
        _flag(quality, "passed")
        checks = quality["checks"]
        assert isinstance(checks, list) and checks
        assert all(isinstance(item, dict) and item.get("passed") is True for item in checks)
        assert workflow_snapshot["quality_checks_executed"] == len(checks)
        drift = _body(artifacts, panel.workflow_id, "twin_observations")["drift"]
        assert isinstance(drift, dict)
        assert drift.get("drifted") is True
        assert drift.get("from_column") == ACCEPTED_FROM_COLUMN
        assert drift.get("to_column") == ACCEPTED_TO_COLUMN
        proposal = _body(artifacts, panel.workflow_id, "repair_proposal")
        assert proposal.get("failure_class") == "SCHEMA_MISMATCH"
        assert proposal.get("from_column") == ACCEPTED_FROM_COLUMN
        assert proposal.get("to_column") == ACCEPTED_TO_COLUMN
        assert proposal.get("artifact_path") == ACCEPTED_ARTIFACT_PATH
        validation = _body(artifacts, panel.workflow_id, "repair_validation")
        assert validation.get("allowed") is True
        diff = validation.get("parsed_diff")
        assert isinstance(diff, dict)
        pairs = diff.get("column_reference_replacements")
        assert isinstance(pairs, list)
        assert [ACCEPTED_FROM_COLUMN, ACCEPTED_TO_COLUMN] in pairs
        application = _body(artifacts, panel.workflow_id, "repair_application")
        assert application.get("applied") is True
        assert workflow_snapshot["repair_count"] == 1
        assert workflow_snapshot["repair_class"] == "SCHEMA_MISMATCH"
        post = _body(artifacts, panel.workflow_id, "post_repair_validation")
        _flag(post, "execute_ok")
        _flag(post, "tests_ok")
        _flag(post, "quality_passed")
        assert panel.incident.revalidation_state == "present"
        assert all(item.outcome == "true" for item in panel.incident.revalidation)
        verdict_body = _body(artifacts, panel.workflow_id, "verifier_verdict")
        verdict = verdict_body.get("verdict")
        assert verdict in {"PASS", "FAIL"}
        assert panel.verification.verdict == verdict
        assert panel.verification.state == "present"
        verdicts.append(str(verdict))
        bundle = _body(artifacts, panel.workflow_id, "evidence_bundle")
        sections = bundle.get("sections")
        assert isinstance(sections, list) and sections
        names = {item.get("name") for item in sections if isinstance(item, dict)}
        assert set(REQUIRED_EVIDENCE_SECTIONS).issubset(names)
    assert model_paths[0] == model_paths[1]
    assert verdicts[0] == verdicts[1] == summary_verifier
    assert summary_verifier == "PASS"
    assert page.workflows[0].models


def _snapshot(
    artifacts: dict[str, dict[str, dict[str, object]]], workflow_id: str
) -> dict[str, object]:
    body = _body(artifacts, workflow_id, "operator_console_snapshot")
    assert body.get("schema_version") == 2
    return body


def _workflow_snapshot(snapshot: dict[str, object], workflow_id: str) -> dict[str, object]:
    rows = snapshot.get("workflows")
    assert isinstance(rows, list)
    for item in rows:
        if isinstance(item, dict) and item.get("workflow_id") == workflow_id:
            return item
    raise AssertionError(workflow_id)
