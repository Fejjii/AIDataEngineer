"""Deterministic interview scorecard and company-facing value metrics."""

from __future__ import annotations

from aide.app.benchmarking.types_local import RunSnapshot
from aide.domain.benchmark import (
    AUTOMATED_ENGINEERING_STEPS,
    BenchmarkVerdict,
    MeasurementClass,
    ScorecardRow,
    ValueMetrics,
)
from aide.domain.verification import VerifierVerdict


def build_scorecard(
    snapshot: RunSnapshot,
    *,
    determinism_pass: bool,
    evidence_complete: bool,
) -> tuple[ScorecardRow, ...]:
    verifier_pass = snapshot.verifier_verdict is VerifierVerdict.PASS
    rows = (
        ScorecardRow(
            name="business_request_to_validated_data_product",
            verdict=_bool_verdict(
                snapshot.parse_ok
                and snapshot.compile_ok
                and snapshot.execute_ok
                and snapshot.tests_ok
                and snapshot.quality_outcome
                and snapshot.reconciliation_outcome
                and verifier_pass
                and snapshot.fail_reason is None
                and snapshot.block_reason is None
            ),
            measurement=MeasurementClass.MEASURED,
            detail="closed loop reached Independent Verifier PASS",
        ),
        ScorecardRow(
            name="schema_drift_detection",
            verdict=_bool_verdict(snapshot.repair_class == "SCHEMA_MISMATCH"),
            measurement=MeasurementClass.MEASURED,
            detail=snapshot.repair_class or "missing",
        ),
        ScorecardRow(
            name="diagnosis_correctness",
            verdict=_bool_verdict(
                snapshot.repair_class == "SCHEMA_MISMATCH"
                and snapshot.from_column == "INVOICE_STATUS"
                and snapshot.to_column == "STATUS"
            ),
            measurement=MeasurementClass.MEASURED,
            detail="INVOICE_STATUS → STATUS",
        ),
        ScorecardRow(
            name="repair_correctness",
            verdict=_bool_verdict(snapshot.repair_count == 1 and snapshot.repair_allowed),
            measurement=MeasurementClass.MEASURED,
            detail=f"applied={snapshot.repair_count}",
        ),
        ScorecardRow(
            name="repair_safety",
            verdict=_bool_verdict(snapshot.repair_allowed and snapshot.repair_count == 1),
            measurement=MeasurementClass.MEASURED,
            detail="one allow-listed column-reference patch",
        ),
        ScorecardRow(
            name="dbt_build_success",
            verdict=_bool_verdict(
                snapshot.parse_ok and snapshot.compile_ok and snapshot.execute_ok
            ),
            measurement=MeasurementClass.MEASURED,
            detail="parse/compile/execute",
        ),
        ScorecardRow(
            name="test_success",
            verdict=_bool_verdict(snapshot.tests_ok),
            measurement=MeasurementClass.MEASURED,
            detail="dbt tests",
        ),
        ScorecardRow(
            name="data_quality_success",
            verdict=_bool_verdict(snapshot.quality_outcome),
            measurement=MeasurementClass.MEASURED,
            detail="interview quality checks",
        ),
        ScorecardRow(
            name="reconciliation_success",
            verdict=_bool_verdict(snapshot.reconciliation_outcome),
            measurement=MeasurementClass.MEASURED,
            detail="revenue and payment totals",
        ),
        ScorecardRow(
            name="verifier_result",
            verdict=_bool_verdict(verifier_pass),
            measurement=MeasurementClass.MEASURED,
            detail=snapshot.verifier_verdict.value if snapshot.verifier_verdict else "missing",
        ),
        ScorecardRow(
            name="human_interventions",
            verdict=_bool_verdict(snapshot.human_intervention_count == 0),
            measurement=MeasurementClass.MEASURED,
            detail=str(snapshot.human_intervention_count),
        ),
        ScorecardRow(
            name="automatic_repair_count",
            verdict=_bool_verdict(snapshot.repair_count == 1),
            measurement=MeasurementClass.MEASURED,
            detail=str(snapshot.repair_count),
        ),
        ScorecardRow(
            name="retries",
            verdict=_bool_verdict(snapshot.retry_count == 0),
            measurement=MeasurementClass.MEASURED,
            detail=str(snapshot.retry_count),
        ),
        ScorecardRow(
            name="wall_clock_duration",
            verdict=BenchmarkVerdict.PASS,
            measurement=MeasurementClass.MEASURED,
            detail=f"{snapshot.wall_clock_duration_ms} ms",
        ),
        ScorecardRow(
            name="estimated_versus_measured_cost",
            verdict=BenchmarkVerdict.PASS,
            measurement=MeasurementClass.UNAVAILABLE,
            detail=(
                "model tokens and warehouse credits UNAVAILABLE offline; classified not invented"
            ),
        ),
        ScorecardRow(
            name="evidence_completeness",
            verdict=_bool_verdict(evidence_complete),
            measurement=MeasurementClass.MEASURED,
            detail=f"{snapshot.evidence_completeness_pct}%",
        ),
        ScorecardRow(
            name="deterministic_repeatability",
            verdict=_bool_verdict(determinism_pass),
            measurement=MeasurementClass.MEASURED,
            detail="two offline runs compared after explicit normalization",
        ),
    )
    return rows


def build_value_metrics(snapshot: RunSnapshot) -> ValueMetrics:
    automated_minutes = sum(minutes for _name, minutes in AUTOMATED_ENGINEERING_STEPS)
    return ValueMetrics(
        relevant_assets_analyzed=len(snapshot.asset_selection),
        models_generated=len(snapshot.model_names),
        governed_tool_operations=snapshot.governed_tool_operations,
        policy_evaluations=snapshot.policy_evaluations,
        detected_incidents=1 if snapshot.repair_class == "SCHEMA_MISMATCH" else 0,
        automatic_repairs=snapshot.repair_count,
        human_interventions=snapshot.human_intervention_count,
        tests_executed=snapshot.tests_executed,
        quality_checks_executed=snapshot.quality_checks_executed,
        evidence_completeness_pct=snapshot.evidence_completeness_pct,
        total_workflow_duration_ms=snapshot.wall_clock_duration_ms,
        repair_duration_ms=snapshot.repair_duration_ms,
        estimated_engineering_steps_automated=len(AUTOMATED_ENGINEERING_STEPS),
        estimated_engineering_minutes_automated=automated_minutes,
    )


def _bool_verdict(passed: bool) -> BenchmarkVerdict:
    return BenchmarkVerdict.PASS if passed else BenchmarkVerdict.FAIL
