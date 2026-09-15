"""Deterministic Interview MVP benchmark runner.

Runs the accepted customer-revenue scenario twice from clean equivalent
starting conditions and compares explicitly normalized stable fields.
PASS/FAIL is never delegated to an LLM.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.evidence import validate_persisted_evidence
from aide.app.benchmarking.normalize import normalized_digest
from aide.app.benchmarking.scorecard import build_scorecard, build_value_metrics
from aide.app.benchmarking.types_local import RunSnapshot
from aide.app.interview import build_interview_stack
from aide.app.supervisor import LEGAL_INTERVIEW_PHASES, InterviewResult
from aide.capabilities.io import Plan
from aide.domain.benchmark import (
    INTERVIEW_REQUEST,
    INTERVIEW_SCENARIO_ID,
    NORMALIZATION_RULES,
    VARIABLE_FINGERPRINT_FIELDS,
    BenchmarkResult,
    BenchmarkRunRecord,
    BenchmarkVerdict,
    ClassifiedMeasurement,
    DeterminismMismatch,
    DeterminismReport,
    LiveSmokeStatus,
    MeasurementClass,
    StableFingerprint,
)
from aide.domain.states import WorkflowState
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, VerifierVerdict
from aide.modelling.constants import REQUIRED_DEMO_MODELS


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _asset_selection(result: InterviewResult) -> tuple[tuple[str, ...], ...]:
    if result.selection is None:
        return ()
    return tuple(tuple(item.asset.address) for item in result.selection.selected)


def _generated_digest(result: InterviewResult) -> str | None:
    generated = result.generated
    if generated is None:
        return None
    return normalized_digest(
        {"files": [{"path": item.path, "content": item.content} for item in generated.files]}
    )


def _plan_digest(result: InterviewResult) -> str:
    plan = result.extra.get("last_plan")
    if isinstance(plan, Plan):
        # Keep every plan field; substitute identifiers instead of dropping them.
        return normalized_digest(plan.model_dump(mode="json"))
    return hashlib.sha256(b"plan").hexdigest()


def _reconciliation_passed(result: InterviewResult) -> bool:
    if result.quality is None:
        return False
    ids = {item.check_id: item.passed for item in result.quality.checks}
    return ids.get("invoice_line_sum_matches_mart", False) and ids.get(
        "payment_sum_matches_mart", False
    )


def _workflow_outcome(result: InterviewResult) -> str:
    if result.failed:
        return "FAILED"
    if result.blocked:
        return "BLOCKED"
    if result.parked:
        return "PARKED"
    if result.verifier is not None and result.verifier.verdict is VerifierVerdict.PASS:
        return "VERIFIED"
    if result.tests_ok and result.quality is not None and result.quality.passed:
        return "VALIDATED"
    return str(result.extra.get("workflow_state") or "UNKNOWN")


def _measurements(
    result: InterviewResult, wall_ms: int, repair_ms: int
) -> tuple[ClassifiedMeasurement, ...]:
    dbt_ms = sum(
        int(ms)
        for name, ms in result.extra.get("step_durations_ms", [])
        if name
        in {
            "parse_transformation",
            "compile_transformation",
            "execute_transformation",
            "run_tests",
            "create_transformation",
        }
    )
    return (
        ClassifiedMeasurement(
            name="wall_clock_duration_ms",
            classification=MeasurementClass.MEASURED,
            value=str(wall_ms),
            unit="ms",
            notes="local workflow wall clock",
        ),
        ClassifiedMeasurement(
            name="step_durations_ms",
            classification=MeasurementClass.MEASURED,
            value=str(len(result.extra.get("step_durations_ms", []))),
            unit="steps",
            notes="per-capability local durations",
        ),
        ClassifiedMeasurement(
            name="repair_duration_ms",
            classification=(
                MeasurementClass.MEASURED
                if "repair_duration_ms" in result.extra
                else MeasurementClass.UNAVAILABLE
            ),
            value=str(repair_ms) if "repair_duration_ms" in result.extra else None,
            unit="ms",
            notes="diagnose through post-repair validation",
        ),
        ClassifiedMeasurement(
            name="dbt_timing_ms",
            classification=MeasurementClass.MEASURED if dbt_ms else MeasurementClass.UNAVAILABLE,
            value=str(dbt_ms) if dbt_ms else None,
            unit="ms",
            notes="local fake or live dbt gateway step durations",
        ),
        ClassifiedMeasurement(
            name="snowflake_query_ms",
            classification=MeasurementClass.UNAVAILABLE,
            value=None,
            unit="ms",
            notes="QUERY_HISTORY is not queried on the offline path",
        ),
        ClassifiedMeasurement(
            name="model_tokens",
            classification=MeasurementClass.UNAVAILABLE,
            value=None,
            notes="Interview MVP uses deterministic modelling; no LLM tokens",
        ),
        ClassifiedMeasurement(
            name="model_cost_usd",
            classification=MeasurementClass.UNAVAILABLE,
            value=None,
            unit="USD",
            notes="no LLM provider in the Interview MVP path",
        ),
        ClassifiedMeasurement(
            name="warehouse_credits",
            classification=MeasurementClass.UNAVAILABLE,
            value=None,
            notes="offline fake warehouse; live credits remain unqueried unless measured",
        ),
    )


def _normalized_context_payload(result: InterviewResult) -> dict[str, Any]:
    selection = _asset_selection(result)
    return {
        "environment": "DEVELOPMENT",
        "asset_selection": [list(item) for item in selection],
        "model_names": list(result.generated.model_names) if result.generated else [],
        "required_demo_models": list(REQUIRED_DEMO_MODELS),
        "phase_sequence": list(result.workflow_states),
    }


def _normalized_evidence_payload(result: InterviewResult) -> dict[str, Any]:
    typed = result.extra.get("typed_evidence", {})
    section_names = tuple(name for name in REQUIRED_EVIDENCE_SECTIONS if name in typed)
    checks = result.verifier.checks if result.verifier else ()
    quality = result.quality.checks if result.quality else ()
    return {
        "required_sections": list(REQUIRED_EVIDENCE_SECTIONS),
        "present_sections": list(section_names),
        "repair_class": result.failure_class.value if result.failure_class else None,
        "repair_count": int(result.extra.get("applied_count", 0)),
        "before_artifact_hash": result.before_artifact_hash,
        "after_artifact_hash": result.after_artifact_hash,
        "generated_content_sha256": _generated_digest(result),
        "plan_digest": _plan_digest(result),
        "verifier_check_vector": [
            [item.check_id, item.passed, item.reason_code] for item in checks
        ],
        "quality_checks": [[item.check_id, item.passed] for item in quality],
        "parse_ok": result.parse_ok,
        "compile_ok": result.compile_ok,
        "execute_ok": result.execute_ok,
        "tests_ok": result.tests_ok,
        "load_ok": result.load_ok,
    }


def build_fingerprint(result: InterviewResult) -> StableFingerprint:
    verifier_vector = tuple(
        (item.check_id, item.passed, item.reason_code)
        for item in (result.verifier.checks if result.verifier else ())
    )
    fixture = None
    loaded = result.extra.get("manifest_load")
    if loaded is not None and getattr(loaded, "fixture_digest", None):
        fixture = str(loaded.fixture_digest)
    return StableFingerprint(
        phase_sequence=tuple(result.workflow_states),
        asset_selection=_asset_selection(result),
        normalized_estate_context_digest=normalized_digest(_normalized_context_payload(result)),
        model_names=result.generated.model_names if result.generated is not None else (),
        generated_content_sha256=_generated_digest(result),
        plan_digest=_plan_digest(result),
        repair_class=result.failure_class.value if result.failure_class else None,
        repair_count=int(result.extra.get("applied_count", 0)),
        test_outcome=result.tests_ok,
        quality_outcome=bool(result.quality and result.quality.passed),
        reconciliation_outcome=_reconciliation_passed(result),
        parse_ok=result.parse_ok,
        compile_ok=result.compile_ok,
        execute_ok=result.execute_ok,
        verifier_verdict=result.verifier.verdict.value if result.verifier else None,
        verifier_check_vector=verifier_vector,
        before_artifact_hash=result.before_artifact_hash,
        after_artifact_hash=result.after_artifact_hash,
        normalized_evidence_digest=normalized_digest(_normalized_evidence_payload(result)),
        fixture_digest=fixture,
        capability_sequence=tuple(
            str(item) for item in result.extra.get("capability_sequence", [])
        ),
        workflow_outcome=_workflow_outcome(result),
    )


def compare_fingerprints(left: StableFingerprint, right: StableFingerprint) -> DeterminismReport:
    left_dump = left.model_dump(mode="json")
    right_dump = right.model_dump(mode="json")
    mismatches: list[DeterminismMismatch] = []
    compared: list[str] = []
    for key in sorted(left_dump):
        compared.append(key)
        if left_dump[key] != right_dump[key]:
            mismatches.append(
                DeterminismMismatch(
                    field=key,
                    left=repr(left_dump[key]),
                    right=repr(right_dump[key]),
                )
            )
    return DeterminismReport(
        equivalent=not mismatches,
        compared_fields=tuple(compared),
        mismatches=tuple(mismatches),
        variable_fields=VARIABLE_FINGERPRINT_FIELDS,
        normalization_rules=NORMALIZATION_RULES,
    )


def _run_snapshot(result: InterviewResult, completeness_pct: int) -> RunSnapshot:
    wall_ms = int(result.extra.get("wall_time_ms", 0))
    if result.started_at is not None:
        wall_ms = max(0, int((_naive_now() - result.started_at).total_seconds() * 1000))
    quality_checks = len(result.quality.checks) if result.quality else 0
    last_tests = result.extra.get("last_tests")
    tests_executed = len(getattr(last_tests, "tests", ()) or ())
    if tests_executed == 0 and (result.tests_ok or result.quality is not None):
        tests_executed = 1
    return RunSnapshot(
        parse_ok=result.parse_ok,
        compile_ok=result.compile_ok,
        execute_ok=result.execute_ok,
        tests_ok=result.tests_ok,
        quality_outcome=bool(result.quality and result.quality.passed),
        reconciliation_outcome=_reconciliation_passed(result),
        fail_reason=result.fail_reason,
        block_reason=result.block_reason,
        repair_class=result.failure_class.value if result.failure_class else None,
        from_column=result.proposal.from_column if result.proposal else None,
        to_column=result.proposal.to_column if result.proposal else None,
        repair_count=int(result.extra.get("applied_count", 0)),
        repair_allowed=bool(result.repair_validation and result.repair_validation.allowed),
        verifier_verdict=result.verifier.verdict if result.verifier else None,
        human_intervention_count=0,
        retry_count=int(result.extra.get("retry_count", 0)),
        wall_clock_duration_ms=wall_ms,
        repair_duration_ms=int(result.extra.get("repair_duration_ms", 0)),
        evidence_completeness_pct=completeness_pct,
        asset_selection=_asset_selection(result),
        model_names=result.generated.model_names if result.generated else (),
        governed_tool_operations=len(result.extra.get("intent_ids", [])),
        policy_evaluations=len(result.extra.get("intent_ids", [])),
        tests_executed=tests_executed,
        quality_checks_executed=quality_checks,
    )


async def record_run(
    session_factory: async_sessionmaker[AsyncSession],
    result: InterviewResult,
) -> BenchmarkRunRecord:
    claimed = result.extra.get("evidence_bundle_sha256")
    claimed_digest = claimed if isinstance(claimed, str) else None
    completeness, persisted_digest = await validate_persisted_evidence(
        session_factory,
        result.workflow_id,
        claimed_bundle_sha256=claimed_digest,
    )
    snapshot = _run_snapshot(result, completeness.completeness_pct)
    fingerprint = build_fingerprint(result)
    wall_ms = snapshot.wall_clock_duration_ms
    bundle = persisted_digest
    return BenchmarkRunRecord(
        workflow_id=result.workflow_id,
        workflow_outcome=_workflow_outcome(result),
        verifier_verdict=result.verifier.verdict if result.verifier else None,
        phase_sequence=tuple(result.workflow_states),
        asset_selection=snapshot.asset_selection,
        estate_context_sha256=result.estate_context_sha256,
        model_names=snapshot.model_names,
        repair_class=snapshot.repair_class,
        repair_count=snapshot.repair_count,
        test_outcome=result.tests_ok,
        quality_outcome=snapshot.quality_outcome,
        reconciliation_outcome=snapshot.reconciliation_outcome,
        evidence_completeness=completeness,
        retry_count=snapshot.retry_count,
        human_intervention_count=snapshot.human_intervention_count,
        tests_executed=snapshot.tests_executed,
        quality_checks_executed=snapshot.quality_checks_executed,
        governed_tool_operations=snapshot.governed_tool_operations,
        policy_evaluations=snapshot.policy_evaluations,
        wall_clock_duration_ms=wall_ms,
        step_durations_ms=tuple(
            (str(name), int(ms)) for name, ms in result.extra.get("step_durations_ms", [])
        ),
        repair_duration_ms=snapshot.repair_duration_ms,
        measurements=_measurements(result, wall_ms, snapshot.repair_duration_ms),
        fingerprint=fingerprint,
        evidence_bundle_sha256=str(bundle) if bundle else None,
        fail_reason=result.fail_reason,
        block_reason=result.block_reason,
    )


def _run_is_accepted(record: BenchmarkRunRecord) -> bool:
    expected_phases = [phase.value for phase in LEGAL_INTERVIEW_PHASES] + [
        WorkflowState.REPAIR.value,
        WorkflowState.EXECUTION.value,
        WorkflowState.VALIDATION.value,
    ]
    return (
        record.fail_reason is None
        and record.block_reason is None
        and record.workflow_outcome == "VERIFIED"
        and record.verifier_verdict is VerifierVerdict.PASS
        and list(record.phase_sequence) == expected_phases
        and record.repair_class == "SCHEMA_MISMATCH"
        and record.repair_count == 1
        and record.test_outcome
        and record.quality_outcome
        and record.reconciliation_outcome
        and record.evidence_completeness.complete
        and set(REQUIRED_DEMO_MODELS).issubset(set(record.model_names))
    )


def assemble_benchmark_result(
    first: BenchmarkRunRecord,
    second: BenchmarkRunRecord,
    *,
    live_smoke: LiveSmokeStatus = LiveSmokeStatus.NOT_RUN,
    live_smoke_detail: str = "",
) -> BenchmarkResult:
    determinism = compare_fingerprints(first.fingerprint, second.fingerprint)
    first_ok = _run_is_accepted(first)
    second_ok = _run_is_accepted(second)
    evidence = first.evidence_completeness
    if not second.evidence_completeness.complete:
        evidence = second.evidence_completeness
    elif not first.evidence_completeness.complete:
        evidence = first.evidence_completeness
    snapshot = RunSnapshot(
        parse_ok=first.fingerprint.parse_ok,
        compile_ok=first.fingerprint.compile_ok,
        execute_ok=first.fingerprint.execute_ok,
        tests_ok=first.test_outcome,
        quality_outcome=first.quality_outcome,
        reconciliation_outcome=first.reconciliation_outcome,
        fail_reason=first.fail_reason,
        block_reason=first.block_reason,
        repair_class=first.repair_class,
        from_column="INVOICE_STATUS",
        to_column="STATUS",
        repair_count=first.repair_count,
        repair_allowed=first.repair_count == 1,
        verifier_verdict=first.verifier_verdict,
        human_intervention_count=first.human_intervention_count,
        retry_count=first.retry_count,
        wall_clock_duration_ms=first.wall_clock_duration_ms,
        repair_duration_ms=first.repair_duration_ms,
        evidence_completeness_pct=evidence.completeness_pct,
        asset_selection=first.asset_selection,
        model_names=first.model_names,
        governed_tool_operations=first.governed_tool_operations,
        policy_evaluations=first.policy_evaluations,
        tests_executed=first.tests_executed,
        quality_checks_executed=first.quality_checks_executed,
    )
    scorecard = build_scorecard(
        snapshot,
        determinism_pass=determinism.equivalent,
        evidence_complete=evidence.complete,
    )
    value = build_value_metrics(snapshot)
    overall = (
        BenchmarkVerdict.PASS
        if first_ok and second_ok and determinism.equivalent and evidence.complete
        else BenchmarkVerdict.FAIL
    )
    return BenchmarkResult(
        scenario_id=INTERVIEW_SCENARIO_ID,
        workflow_outcome=first.workflow_outcome,
        verifier_verdict=first.verifier_verdict,
        verdict=overall,
        runs=(first, second),
        determinism=determinism,
        scorecard=scorecard,
        value_metrics=value,
        evidence_completeness=evidence,
        live_smoke=live_smoke,
        live_smoke_detail=live_smoke_detail,
    )


async def run_interview_once(
    session_factory: async_sessionmaker[AsyncSession],
    work_root: Path,
    *,
    requirement: str = INTERVIEW_REQUEST,
) -> InterviewResult:
    supervisor = build_interview_stack(session_factory, work_root=work_root)
    return await supervisor.run_customer_revenue(requirement, include_schema_drift=True)


async def run_offline_benchmark(
    session_factory: async_sessionmaker[AsyncSession],
    work_root: Path,
    *,
    requirement: str = INTERVIEW_REQUEST,
    live_smoke: LiveSmokeStatus = LiveSmokeStatus.NOT_RUN,
    live_smoke_detail: str = "",
) -> tuple[BenchmarkResult, InterviewResult, InterviewResult]:
    first_result = await run_interview_once(
        session_factory, work_root / "run-1", requirement=requirement
    )
    first = await record_run(session_factory, first_result)
    second_result = await run_interview_once(
        session_factory, work_root / "run-2", requirement=requirement
    )
    second = await record_run(session_factory, second_result)
    report = assemble_benchmark_result(
        first,
        second,
        live_smoke=live_smoke,
        live_smoke_detail=live_smoke_detail,
    )
    return report, first_result, second_result


__all__ = [
    "assemble_benchmark_result",
    "build_fingerprint",
    "compare_fingerprints",
    "record_run",
    "run_interview_once",
    "run_offline_benchmark",
]
