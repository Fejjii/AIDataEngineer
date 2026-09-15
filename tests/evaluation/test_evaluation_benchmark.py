"""Benchmark measurement classification. Do not invent financial ROI."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.demo import render_demo_report, render_scorecard
from aide.app.benchmarking.runner import run_offline_benchmark
from aide.domain.benchmark import MeasurementClass


@pytest.mark.asyncio
async def test_e_bm_01_measurement_classes_are_honest(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    report, first, _second = await run_offline_benchmark(session_factory, tmp_path)
    classifications = {item.name: item for item in report.runs[0].measurements}
    assert classifications["wall_clock_duration_ms"].classification is MeasurementClass.MEASURED
    assert classifications["wall_clock_duration_ms"].value is not None
    assert classifications["model_tokens"].classification is MeasurementClass.UNAVAILABLE
    assert classifications["model_tokens"].value is None
    assert classifications["model_cost_usd"].classification is MeasurementClass.UNAVAILABLE
    assert classifications["model_cost_usd"].value is None
    assert classifications["warehouse_credits"].classification is MeasurementClass.UNAVAILABLE
    assert classifications["warehouse_credits"].value is None
    estimated = report.value_metrics.estimated_engineering_minutes_automated
    assert estimated > 0
    demo = render_demo_report(first, report)
    scorecard = render_scorecard(report)
    assert "ESTIMATED" in scorecard
    assert "UNAVAILABLE" in demo
    assert "MEASURED" in demo
    assert "ROI" not in demo.upper()
    assert "ROI" not in scorecard.upper()
    assert "return on investment" not in demo.lower()
    for item in report.runs[0].measurements:
        if item.classification is MeasurementClass.UNAVAILABLE:
            assert item.value is None
        if item.classification is MeasurementClass.MEASURED:
            assert item.value is not None
