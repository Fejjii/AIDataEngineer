"""Aggregate scenario results into a deterministic evaluation matrix. No LLM judge."""

from __future__ import annotations

from aide.app.evaluation.catalog import CATEGORY_OPTIONAL, CATEGORY_REQUIRED
from aide.domain.benchmark import MeasurementClass
from aide.domain.evaluation import (
    CategoryScore,
    EvaluationCategory,
    EvaluationReport,
    EvaluationVerdict,
    MvpReadiness,
    ScenarioResult,
)


def _index(results: tuple[ScenarioResult, ...]) -> dict[str, ScenarioResult]:
    return {item.scenario_id: item for item in results}


def _verdict_for(
    by_id: dict[str, ScenarioResult],
    required: tuple[str, ...],
    optional: tuple[str, ...],
) -> tuple[EvaluationVerdict, tuple[str, ...], str]:
    required_hits = [by_id[sid] for sid in required if sid in by_id]
    optional_hits = [by_id[sid] for sid in optional if sid in by_id]
    combined = required_hits + optional_hits
    used = tuple(item.scenario_id for item in combined)
    failed = [item.scenario_id for item in combined if item.verdict is EvaluationVerdict.FAIL]
    if failed:
        return EvaluationVerdict.FAIL, used, "FAIL scenarios: " + ",".join(failed)
    missing_required = [sid for sid in required if sid not in by_id]
    not_tested_required = [
        item.scenario_id for item in required_hits if item.verdict is EvaluationVerdict.NOT_TESTED
    ]
    if missing_required or not_tested_required or not required_hits:
        detail = ",".join([*missing_required, *not_tested_required]) or "none executed"
        return (
            EvaluationVerdict.NOT_TESTED,
            used,
            "required scenarios missing or NOT TESTED: " + detail,
        )
    optional_notes = [
        f"{item.scenario_id}={item.verdict.value}"
        for item in optional_hits
        if item.verdict is not EvaluationVerdict.PASS
    ]
    evidence = "required scenarios PASS"
    if optional_notes:
        evidence = evidence + "; optional " + "; ".join(optional_notes)
    return EvaluationVerdict.PASS, used, evidence


def score_categories(results: tuple[ScenarioResult, ...]) -> tuple[CategoryScore, ...]:
    by_id = _index(results)
    scores: list[CategoryScore] = []
    for category in EvaluationCategory:
        required = CATEGORY_REQUIRED.get(category, ())
        optional = CATEGORY_OPTIONAL.get(category, ())
        verdict, used, evidence = _verdict_for(by_id, required, optional)
        scores.append(
            CategoryScore(
                category=category,
                verdict=verdict,
                evidence=evidence,
                scenario_ids=used,
                measurement=MeasurementClass.MEASURED,
            )
        )
    return tuple(scores)


def readiness_from_categories(
    scores: tuple[CategoryScore, ...],
    scenarios: tuple[ScenarioResult, ...] = (),
) -> MvpReadiness:
    if any(item.verdict is EvaluationVerdict.FAIL for item in scores):
        return MvpReadiness.NOT_PRESENTABLE
    if any(item.verdict is EvaluationVerdict.NOT_TESTED for item in scores):
        return MvpReadiness.NOT_PRESENTABLE
    live = next((item for item in scenarios if item.scenario_id == "E-LP-LIVE"), None)
    if live is None or live.verdict is EvaluationVerdict.NOT_TESTED:
        return MvpReadiness.PRESENTABLE_OFFLINE_CREDENTIAL_GATED
    return MvpReadiness.PRESENTABLE


def build_evaluation_report(
    *,
    task_id: str,
    scenarios: tuple[ScenarioResult, ...],
    defects_found: tuple[str, ...] = (),
    defects_fixed: tuple[str, ...] = (),
    remaining_risks: tuple[str, ...] = (),
    known_limitations: tuple[str, ...] = (),
    benchmark_summary: str,
    performance_summary: str,
) -> EvaluationReport:
    categories = score_categories(scenarios)
    return EvaluationReport(
        task_id=task_id,
        readiness=readiness_from_categories(categories, scenarios),
        categories=categories,
        scenarios=scenarios,
        defects_found=defects_found,
        defects_fixed=defects_fixed,
        remaining_risks=remaining_risks,
        known_limitations=known_limitations,
        benchmark_summary=benchmark_summary,
        performance_summary=performance_summary,
    )


__all__ = ["build_evaluation_report", "readiness_from_categories", "score_categories"]
