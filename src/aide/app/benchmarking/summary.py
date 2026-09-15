"""Bounded Interview MVP demo summary. Reuses benchmark records; no env leakage."""

from __future__ import annotations

from aide.app.supervisor import InterviewResult
from aide.domain.benchmark import (
    INTERVIEW_SCENARIO_ID,
    BenchmarkResult,
    DigitalTwinSummary,
    InterviewDemoSummary,
    RepairResultSummary,
    SchemaDriftSummary,
)
from aide.domain.repair import (
    ACCEPTED_ARTIFACT_PATH,
    ACCEPTED_ASSET_ADDRESS,
    ACCEPTED_FROM_COLUMN,
    ACCEPTED_TO_COLUMN,
)


def summarize_interview_demo(
    report: BenchmarkResult,
    first: InterviewResult,
) -> InterviewDemoSummary:
    """Project the accepted synthetic scenario into a recruiter-safe payload."""
    first_run = report.runs[0]
    if first.selection is not None:
        selected = tuple(".".join(item.asset.address) for item in first.selection.selected)
    else:
        selected = tuple(".".join(item) for item in first_run.asset_selection)
    snapshot = first.twin_snapshot
    mapping = f"{ACCEPTED_FROM_COLUMN} → {ACCEPTED_TO_COLUMN}"
    detected = first_run.repair_class == "SCHEMA_MISMATCH"
    allowed = bool(first.repair_validation is not None and first.repair_validation.allowed)
    applied = bool(first.repair_application is not None and first.repair_application.applied)
    return InterviewDemoSummary(
        scenario_id=report.scenario_id or INTERVIEW_SCENARIO_ID,
        workflow_status=report.workflow_outcome,
        workflow_ids=tuple(str(item.workflow_id) for item in report.runs),
        digital_twin=DigitalTwinSummary(
            snapshot_id=str(snapshot.twin_snapshot_id) if snapshot is not None else None,
            manifest_sha256=snapshot.manifest_sha256 if snapshot is not None else None,
            estate_context_sha256=first.estate_context_sha256,
            pinned_asset_count=len(snapshot.asset_versions) if snapshot is not None else 0,
            selected_assets=selected,
        ),
        schema_drift=SchemaDriftSummary(
            detected=detected,
            failure_class=first_run.repair_class,
            mapping=mapping,
            asset=".".join(ACCEPTED_ASSET_ADDRESS),
        ),
        repair=RepairResultSummary(
            applied=applied,
            apply_count=first_run.repair_count,
            allowed=allowed,
            artifact_path=ACCEPTED_ARTIFACT_PATH,
        ),
        verifier_verdict=(
            report.verifier_verdict.value if report.verifier_verdict is not None else None
        ),
        evidence_completeness_pct=report.evidence_completeness.completeness_pct,
        evidence_complete=report.evidence_completeness.complete,
        determinism=report.determinism.equivalent,
        benchmark_verdict=report.verdict.value,
        benchmark_metrics=report.value_metrics,
        live_smoke=report.live_smoke,
    )


__all__ = ["summarize_interview_demo"]
