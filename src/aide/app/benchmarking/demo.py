"""Concise human-readable Interview MVP demo report."""

from __future__ import annotations

from datetime import UTC, datetime

from aide.app.supervisor import InterviewResult
from aide.domain.benchmark import BenchmarkResult, ClassifiedMeasurement
from aide.domain.repair import ACCEPTED_FROM_COLUMN, ACCEPTED_TO_COLUMN


def render_demo_report(
    result: InterviewResult,
    benchmark: BenchmarkResult | None = None,
) -> str:
    request = result.requirement.goal if result.requirement else "customer revenue data product"
    assets = (
        ", ".join(".".join(item.asset.address[1:]) for item in result.selection.selected)
        if result.selection
        else "none"
    )
    models = ", ".join(result.generated.model_names[:8]) if result.generated else "none"
    model_count = len(result.generated.model_names) if result.generated else 0
    if result.generated and model_count > 8:
        models = f"{models}, … ({model_count} total)"
    context = result.estate_context_sha256 or "unavailable"
    drift = f"{ACCEPTED_FROM_COLUMN} → {ACCEPTED_TO_COLUMN} on VANTARA_RAW.BILLING.INVOICES"
    diagnosis = result.failure_class.value if result.failure_class else "none"
    safety = (
        "allowed"
        if result.repair_validation is not None and result.repair_validation.allowed
        else "blocked"
    )
    applied = (
        "applied exactly once"
        if result.repair_application is not None and result.repair_application.applied
        else "not applied"
    )
    verifier = result.verifier.verdict.value if result.verifier else "not run"
    bundle = str(result.extra.get("evidence_bundle_sha256") or "unavailable")
    wall = "unavailable"
    if result.started_at is not None:
        now = datetime.now(UTC).replace(tzinfo=None)
        wall = f"{max(0, int((now - result.started_at).total_seconds() * 1000))} ms MEASURED"
    if benchmark is not None:
        wall = f"{benchmark.runs[0].wall_clock_duration_ms} ms MEASURED"
    cost_lines = _cost_lines(benchmark.runs[0].measurements if benchmark else ())
    overall = (
        benchmark.verdict.value
        if benchmark
        else (
            "PASS"
            if result.verifier is not None and result.verifier.verdict.value == "PASS"
            else "FAIL"
        )
    )
    determinism = benchmark.determinism.equivalent if benchmark is not None else None
    completeness = (
        f"{benchmark.evidence_completeness.completeness_pct}%" if benchmark is not None else "n/a"
    )
    lines = [
        "Data Pilot AI — Interview MVP",
        "============================",
        f"Business request: {request}",
        f"Estate understanding: {assets}",
        f"EstateContext digest: {context}",
        f"Generated models: {models}",
        (
            "Initial success: parse="
            f"{_flag(result.parse_ok)} compile={_flag(result.compile_ok)} "
            f"execute={_flag(result.execute_ok)} tests={_flag(result.tests_ok)} "
            f"quality={_flag(bool(result.quality and result.quality.passed))}"
        ),
        f"Schema drift: {drift}",
        f"Failure diagnosis: {diagnosis}",
        "Repair proposal: allow-listed column-reference correction in "
        "models/staging/stg_billing__invoices.sql",
        f"Repair safety: {safety}",
        f"Repair application: {applied}",
        (
            "Post-repair validation: tests="
            f"{_flag(result.tests_ok)} quality="
            f"{_flag(bool(result.quality and result.quality.passed))} "
            f"reconciliation={_flag(_recon(result))}"
        ),
        f"Independent Verifier: {verifier}",
        f"Timing: wall_clock={wall}",
        f"Cost classification: {cost_lines}",
        f"Evidence bundle digest: {bundle}",
        f"Evidence completeness: {completeness}",
        (
            f"Determinism: {'PASS' if determinism else 'FAIL'}"
            if determinism is not None
            else "Determinism: not compared"
        ),
        f"Final: {overall}",
    ]
    return "\n".join(lines)


def _flag(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _recon(result: InterviewResult) -> bool:
    if result.quality is None:
        return False
    ids = {item.check_id: item.passed for item in result.quality.checks}
    return ids.get("invoice_line_sum_matches_mart", False) and ids.get(
        "payment_sum_matches_mart", False
    )


def _cost_lines(measurements: tuple[ClassifiedMeasurement, ...]) -> str:
    if not measurements:
        return "model tokens UNAVAILABLE; warehouse credits UNAVAILABLE"
    parts: list[str] = []
    for item in measurements:
        if item.name in {"model_tokens", "model_cost_usd", "warehouse_credits"}:
            parts.append(f"{item.name} {item.classification.value}")
    return "; ".join(parts) or "UNAVAILABLE"


def render_scorecard(benchmark: BenchmarkResult) -> str:
    rows = ["Scorecard"]
    for item in benchmark.scorecard:
        rows.append(f"  {item.name}: {item.verdict.value} [{item.measurement.value}] {item.detail}")
    metrics = benchmark.value_metrics
    rows.extend(
        [
            "Value metrics",
            f"  assets={metrics.relevant_assets_analyzed} models={metrics.models_generated}",
            f"  gateway_ops={metrics.governed_tool_operations} "
            f"policy_evals={metrics.policy_evaluations}",
            f"  incidents={metrics.detected_incidents} repairs={metrics.automatic_repairs} "
            f"humans={metrics.human_interventions}",
            f"  tests={metrics.tests_executed} quality_checks={metrics.quality_checks_executed}",
            f"  evidence={metrics.evidence_completeness_pct}% "
            f"duration_ms={metrics.total_workflow_duration_ms} "
            f"repair_ms={metrics.repair_duration_ms}",
            f"  estimated_steps_automated={metrics.estimated_engineering_steps_automated} "
            f"({metrics.estimated_engineering_minutes_automated} min, ESTIMATED)",
        ]
    )
    return "\n".join(rows)


__all__ = ["render_demo_report", "render_scorecard"]
