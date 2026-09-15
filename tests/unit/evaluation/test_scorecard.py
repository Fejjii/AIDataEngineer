"""Deterministic evaluation scorecard aggregation. No LLM judge."""

from __future__ import annotations

from aide.app.evaluation.report import render_evaluation_markdown
from aide.app.evaluation.scorecard import build_evaluation_report, readiness_from_categories
from aide.domain.benchmark import MeasurementClass
from aide.domain.evaluation import (
    CategoryScore,
    EvaluationCategory,
    EvaluationVerdict,
    MvpReadiness,
    ScenarioResult,
)


def _scenario(
    scenario_id: str,
    category: EvaluationCategory,
    verdict: EvaluationVerdict = EvaluationVerdict.PASS,
) -> ScenarioResult:
    return ScenarioResult(
        scenario_id=scenario_id,
        name=scenario_id,
        category=category,
        verdict=verdict,
        evidence="fixture",
        measurement=MeasurementClass.MEASURED,
    )


def test_any_fail_makes_mvp_not_presentable() -> None:
    scores = (
        CategoryScore(
            category=EvaluationCategory.FUNCTIONAL_CORRECTNESS,
            verdict=EvaluationVerdict.FAIL,
            evidence="boom",
            scenario_ids=("E-HP-01",),
        ),
    )
    assert readiness_from_categories(scores) is MvpReadiness.NOT_PRESENTABLE


def test_missing_live_is_credential_gated_presentable() -> None:
    required = {
        EvaluationCategory.FUNCTIONAL_CORRECTNESS: ("E-HP-01",),
        EvaluationCategory.REPAIR_CORRECTNESS: ("E-HP-01",),
        EvaluationCategory.REPAIR_SAFETY: (
            "E-SF-SECOND",
            "E-SF-RECUR",
            "E-SF-BROADER",
            "E-SF-TABLE",
            "E-SF-COL",
            "E-SF-TYPE",
            "E-SF-TEST",
        ),
        EvaluationCategory.POLICY_ENFORCEMENT: ("E-SF-PERM", "E-SF-PROD", "E-SF-BYPASS"),
        EvaluationCategory.LEAST_PRIVILEGE: ("E-LP-RO", "E-LP-GRANT", "E-SF-RAW"),
        EvaluationCategory.EVIDENCE_INTEGRITY: (
            "E-TM-SECTION",
            "E-TM-BUNDLE",
            "E-TM-WF",
            "E-TM-SNAP",
            "E-TM-MODE",
            "E-TM-DRIFT",
            "E-TM-HASH",
        ),
        EvaluationCategory.DETERMINISM: ("E-RP-01", "E-BM-01"),
        EvaluationCategory.RECOVERY: (
            "E-RC-PHASE",
            "E-RC-INTENT",
            "E-RC-BUDGET",
            "E-RC-EVID",
            "E-RC-VER",
            "E-RC-AMBIG",
        ),
        EvaluationCategory.TEST_SUCCESS: ("E-HP-01", "E-FI-TEST"),
        EvaluationCategory.DATA_QUALITY: ("E-HP-01", "E-FI-QUAL"),
        EvaluationCategory.RECONCILIATION: ("E-HP-01",),
        EvaluationCategory.VERIFIER_CORRECTNESS: (
            "E-HP-01",
            "E-PR-MIX",
            "E-PR-REAL",
            "E-PR-MOCK",
        ),
        EvaluationCategory.PERFORMANCE: ("E-PF-01",),
        EvaluationCategory.HUMAN_INTERVENTION_COUNT: ("E-HP-01",),
        EvaluationCategory.KNOWN_LIMITATIONS: ("E-LIM-01",),
    }
    scenarios = []
    for category, ids in required.items():
        for sid in ids:
            scenarios.append(_scenario(sid, category))
    scenarios.append(
        _scenario(
            "E-LP-LIVE",
            EvaluationCategory.LEAST_PRIVILEGE,
            EvaluationVerdict.NOT_TESTED,
        )
    )
    report = build_evaluation_report(
        task_id="FINAL-QA-001",
        scenarios=tuple(scenarios),
        benchmark_summary="offline twice",
        performance_summary="observed",
    )
    assert report.readiness is MvpReadiness.PRESENTABLE_OFFLINE_CREDENTIAL_GATED
    assert all(row.verdict is not EvaluationVerdict.FAIL for row in report.categories)
    markdown = render_evaluation_markdown(report)
    assert "`PRESENTABLE_OFFLINE_CREDENTIAL_GATED`" in markdown
    assert "E-HP-01" in markdown


def test_missing_required_scenario_is_not_tested() -> None:
    report = build_evaluation_report(
        task_id="FINAL-QA-001",
        scenarios=(),
        benchmark_summary="none",
        performance_summary="none",
    )
    assert all(row.verdict is EvaluationVerdict.NOT_TESTED for row in report.categories)
    assert report.readiness is MvpReadiness.NOT_PRESENTABLE
