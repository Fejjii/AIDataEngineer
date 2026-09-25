"""Fail closed when persisted showcase evidence is missing."""

from __future__ import annotations

from tests.evaluation.showcase_summary import format_showcase_summary, summary_from_run_page

from aide.app.console.present import RunPage


def _page(**overrides: object) -> RunPage:
    values: dict[str, object] = {
        "run_id": "run",
        "status": "completed",
        "error_message": "",
        "started_at": "",
        "finished_at": "",
        "execution_label": "synthetic",
        "business_correctness": "NOT_VALIDATED",
        "limitations": (),
        "benchmark_verdict": "unavailable",
        "workflow_outcome": "unavailable",
        "determinism": "unavailable",
        "evidence_completeness": "unavailable",
        "evidence_complete": "unavailable",
        "summary": (),
        "workflows": (),
        "audit_events": (),
        "running_note": "",
    }
    values.update(overrides)
    return RunPage(**values)  # type: ignore[arg-type]


def test_missing_evidence_is_not_recorded_as_pass() -> None:
    text = format_showcase_summary(summary_from_run_page(_page()))
    assert "verifier: unavailable" in text
    assert "business correctness: NOT_VALIDATED" in text
    assert "verifier: PASS" not in text
    assert "business correctness: PASS" not in text
    assert "Digital Twin: unavailable" in text
    assert "models: unavailable" in text
    assert "repair: unavailable" in text


def test_verifier_pass_stays_distinct_from_business_correctness() -> None:
    summary = summary_from_run_page(_page())
    rendered = format_showcase_summary(summary)
    verifier_line = next(line for line in rendered.splitlines() if line.startswith("verifier:"))
    business_line = next(
        line for line in rendered.splitlines() if line.startswith("business correctness:")
    )
    assert verifier_line != "verifier: PASS"
    assert business_line == "business correctness: NOT_VALIDATED"
    assert business_line.rsplit(": ", 1)[-1] != "PASS"
