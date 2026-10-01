"""Exercise the real Jinja pages with stored evidence, without a database."""

from __future__ import annotations

from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from tests.unit.console.test_console_presentation import _artifacts, _page, _snapshot

from aide.app.console.present import RunSummary, build_dashboard
from aide.app.console.sources import group_source_catalog, load_source_catalog
from aide.domain.benchmark import (
    INTERVIEW_REQUEST,
    INTERVIEW_SCENARIO_ID,
    OPERATOR_BUSINESS_CORRECTNESS,
    OPERATOR_EXECUTION_LABEL,
    OPERATOR_LIMITATIONS,
)
from aide.domain.repair import (
    ACCEPTED_ARTIFACT_PATH,
    ACCEPTED_ASSET_ADDRESS,
    ACCEPTED_FROM_COLUMN,
    ACCEPTED_TO_COLUMN,
)
from aide.persistence.console import SNAPSHOT_ARTIFACT_TYPE

_TEMPLATES = Path(__file__).resolve().parents[3] / "src/aide/api/templates"
_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES),
    autoescape=select_autoescape(["html", "xml"]),
    undefined=StrictUndefined,
)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "wbr"}


class _PageHTML(HTMLParser):
    """Catch invalid nesting and distinguish initially visible evidence from details."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.stack: list[tuple[str, dict[str, str | None]]] = []
        self.nodes: list[tuple[str, dict[str, str | None], bool]] = []
        self.visible_text: list[str] = []
        self.ids: list[str] = []
        self.anchors: list[str] = []
        self.feed(html)
        assert not self.stack
        assert len(self.ids) == len(set(self.ids))
        assert set(self.anchors) <= set(self.ids)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        hidden = any(t == "details" and "open" not in a for t, a in self.stack)
        self.nodes.append((tag, attributes, hidden))
        if identifier := attributes.get("id"):
            self.ids.append(identifier)
        if tag == "a" and (href := attributes.get("href")) and href.startswith("#"):
            self.anchors.append(href[1:])
        if tag not in _VOID:
            self.stack.append((tag, attributes))

    def handle_endtag(self, tag: str) -> None:
        assert self.stack and self.stack[-1][0] == tag, (tag, self.stack[-3:])
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if not any(t in {"style", "details"} for t, _ in self.stack):
            self.visible_text.append(data)


def _home(runs: tuple[RunSummary, ...] = ()) -> str:
    return _ENV.get_template("home.html").render(
        dashboard=build_dashboard(runs),
        estate=group_source_catalog(load_source_catalog()),
        csrf_token="test-csrf",
        scenario_id=INTERVIEW_SCENARIO_ID,
        business_objective=INTERVIEW_REQUEST,
        execution_label=OPERATOR_EXECUTION_LABEL,
        business_correctness=OPERATOR_BUSINESS_CORRECTNESS,
        limitations=OPERATOR_LIMITATIONS,
        drift_from=ACCEPTED_FROM_COLUMN,
        drift_to=ACCEPTED_TO_COLUMN,
        drift_asset=".".join(ACCEPTED_ASSET_ADDRESS),
        repair_path=ACCEPTED_ARTIFACT_PATH,
    )


@pytest.mark.parametrize("status", ["empty", "completed", "running", "failed"])
def test_overview_keeps_objective_action_and_separate_judgements(status: str) -> None:
    runs = (
        ()
        if status == "empty"
        else (RunSummary("run-id", status, "stored-start", "", 2, verifier_verdict="FAIL"),)
    )
    html = _home(runs)
    parsed = _PageHTML(html)
    visible = " ".join(parsed.visible_text)
    assert INTERVIEW_REQUEST in visible
    assert "VALIDATED_SYNTHETIC_CONTRACT" in visible
    assert "production financial correctness" in visible
    assert html.index('id="scenario"') < html.index('class="panel latest-run"')
    assert html.index('class="panel latest-run"') < html.index('id="estate"')
    start_forms = [
        a for t, a, _ in parsed.nodes if t == "form" and a.get("action") == "/console/runs"
    ]
    assert len(start_forms) == (0 if status == "running" else 1)
    if status == "completed":
        assert "FAIL" in visible
        assert "/console/runs/run-id#summary" in html
    if status == "running":
        assert "View running workflow" in visible


@pytest.mark.parametrize(
    "artifacts",
    [_artifacts(), _artifacts("FAIL"), {}, {SNAPSHOT_ARTIFACT_TYPE: _snapshot(version=1)}],
)
def test_run_results_visible_and_secondary_evidence_disclosed(artifacts: dict[str, Any]) -> None:
    page = _page(artifacts)
    html = _ENV.get_template("run.html").render(page=page, csrf_token="test-csrf")
    parsed = _PageHTML(html)
    visible = " ".join(parsed.visible_text)
    assert page.what_happened in visible
    assert "VALIDATED_SYNTHETIC_CONTRACT" in visible
    assert "not production financial validation" in visible
    signals = [(a["data-signal"], hidden) for _, a, hidden in parsed.nodes if "data-signal" in a]
    assert signals == [("technical", False), ("verification", False), ("business", False)]
    metrics = {a["data-metric"]: hidden for _, a, hidden in parsed.nodes if "data-metric" in a}
    assert metrics["models"] is False
    assert metrics["human"] is False
    assert metrics["governed"] is True
    assert metrics["policy"] is True
    assert metrics["determinism"] is True
    stages = [a["data-key"] for _, a, hidden in parsed.nodes if "data-key" in a and not hidden]
    assert stages == [stage.key for stage in page.primary.timeline]
    if page.primary.incident.state == "present":
        assert "INVOICE_STATUS → STATUS" in visible
        assert "applied once" in visible
        assert "Original SQL" in visible and "Repaired SQL" in visible
    if page.primary.verification.verdict == "FAIL":
        assert "UNRECONCILED" in visible
    if not artifacts:
        assert "without human intervention" not in visible
        assert "applied one bounded repair" not in visible


@pytest.mark.parametrize("status", ["running", "failed"])
def test_run_without_workflow_does_not_claim_success(status: str) -> None:
    page = replace(
        _page({}),
        status=status,
        workflows=(),
        error_message="failure" if status == "failed" else "",
    )
    html = _ENV.get_template("run.html").render(page=page, csrf_token="test-csrf")
    parsed = _PageHTML(html)
    assert not any("data-key" in a for _, a, _ in parsed.nodes)
    assert 'data-narrative="present"' not in html
    assert ('http-equiv="refresh"' in html) == (status == "running")


def test_sql_failure_and_preview_text_remain_escaped() -> None:
    artifacts = _artifacts()
    artifacts[SNAPSHOT_ARTIFACT_TYPE]["workflows"][0]["output_preview"]["rows"][0][
        "customer_sk"
    ] = '<script>alert("preview")</script>'
    artifacts["repair_proposal"]["patched_sql"] = '<script>alert("sql")</script>'
    page = replace(_page(artifacts), error_message='<script>alert("error")</script>')
    html = _ENV.get_template("run.html").render(page=page, csrf_token="test-csrf")
    parsed = _PageHTML(html)
    assert not any(t == "script" for t, _, _ in parsed.nodes)
    assert "&lt;script&gt;" in html
    assert 'tabindex="0" aria-label="Repaired SQL"' in html


@pytest.mark.parametrize("configured", [True, False])
def test_login_overrides_chrome_without_a_broken_skip_link(configured: bool) -> None:
    html = _ENV.get_template("login.html").render(
        configured=configured, login_token="test-login", error=""
    )
    parsed = _PageHTML(html)
    assert not parsed.anchors
    assert not any(a.get("class") == "skip-link" for _, a, _ in parsed.nodes)
    assert ('name="password"' in html) == configured


def test_denied_page_retains_a_valid_skip_target_and_escaped_detail() -> None:
    html = _ENV.get_template("denied.html").render(detail="<script>denied</script>", active_nav="")
    parsed = _PageHTML(html)
    assert "main-content" in parsed.anchors
    assert not any(t == "script" for t, _, _ in parsed.nodes)
