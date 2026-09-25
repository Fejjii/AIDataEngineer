"""Concise recruiter summary built only from typed console results.

Unavailable evidence stays unavailable. A verifier PASS is never copied into
the business-correctness field.
"""

from __future__ import annotations

from dataclasses import dataclass

from aide.app.console.present import RunPage

_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ShowcaseResultSummary:
    """One showcase smoke result. Values are copied, not invented."""

    run_status: str
    workflow_outcome: str
    digital_twin: str
    models: str
    tests: str
    quality: str
    incident: str
    repair: str
    verifier: str
    evidence: str
    determinism: str
    business_correctness: str


def summary_from_run_page(page: RunPage) -> ShowcaseResultSummary:
    """Read a persisted run page. Missing panels stay unavailable."""
    primary = page.primary
    if primary is None:
        return ShowcaseResultSummary(
            run_status=_text(page.status),
            workflow_outcome=_text(page.workflow_outcome),
            digital_twin=_UNAVAILABLE,
            models=_UNAVAILABLE,
            tests=_UNAVAILABLE,
            quality=_UNAVAILABLE,
            incident=_UNAVAILABLE,
            repair=_UNAVAILABLE,
            verifier=_UNAVAILABLE,
            evidence=_evidence(page),
            determinism=_text(page.determinism),
            business_correctness=_text(page.business_correctness),
        )
    twin = primary.twin
    digital_twin = _UNAVAILABLE
    if twin.state == "present":
        digital_twin = f"snapshot {twin.snapshot_id} assets {twin.pinned_asset_count}"
    models = _UNAVAILABLE
    if primary.models:
        models = f"{len(primary.models)} model files"
    tests = _UNAVAILABLE
    if primary.quality.tests_state == "present":
        tests = (
            f"{primary.quality.tests_passed}/{primary.quality.tests_total} passed; "
            f"aggregate {primary.quality.aggregate_test_flag}"
        )
    quality = _UNAVAILABLE
    if primary.quality.quality_state == "present":
        quality = (
            f"passed={primary.quality.quality_passed} "
            f"checks={len(primary.quality.all_quality_checks)}"
        )
    incident = primary.incident
    incident_text = _UNAVAILABLE
    if incident.state == "present":
        incident_text = f"{incident.failure_class} {incident.from_column} → {incident.to_column}"
    repair = _UNAVAILABLE
    if incident.repair_applied != _UNAVAILABLE:
        repair = (
            f"applied={incident.repair_applied} count={incident.repair_count} "
            f"path={incident.repair_path}"
        )
    verifier = _UNAVAILABLE
    if primary.verification.state == "present":
        verifier = _text(primary.verification.verdict)
    return ShowcaseResultSummary(
        run_status=_text(page.status),
        workflow_outcome=_text(page.workflow_outcome),
        digital_twin=digital_twin,
        models=models,
        tests=tests,
        quality=quality,
        incident=incident_text,
        repair=repair,
        verifier=verifier,
        evidence=_evidence(page),
        determinism=_text(page.determinism),
        business_correctness=_text(page.business_correctness),
    )


def format_showcase_summary(summary: ShowcaseResultSummary) -> str:
    """Render the twelve contract lines. Does not add a verdict of its own."""
    rows = (
        ("run status", summary.run_status),
        ("workflow outcome", summary.workflow_outcome),
        ("Digital Twin", summary.digital_twin),
        ("models", summary.models),
        ("tests", summary.tests),
        ("quality", summary.quality),
        ("incident", summary.incident),
        ("repair", summary.repair),
        ("verifier", summary.verifier),
        ("evidence", summary.evidence),
        ("determinism", summary.determinism),
        ("business correctness", summary.business_correctness),
    )
    return "\n".join(f"{label}: {value}" for label, value in rows)


def _evidence(page: RunPage) -> str:
    if page.evidence_completeness == _UNAVAILABLE and page.evidence_complete == _UNAVAILABLE:
        return _UNAVAILABLE
    return f"complete={page.evidence_complete} completeness={page.evidence_completeness}"


def _text(value: str) -> str:
    stripped = value.strip()
    return stripped if stripped else _UNAVAILABLE
