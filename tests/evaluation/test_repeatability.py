"""E-RP-01 repeatability after documented fingerprint normalization."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.runner import run_offline_benchmark
from aide.domain.benchmark import BenchmarkVerdict


@pytest.mark.asyncio
async def test_e_rp_01_benchmark_runs_twice_with_stable_normalized_fingerprints(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    report, first, second = await run_offline_benchmark(session_factory, tmp_path)
    assert first.fail_reason is None, first.fail_reason
    assert second.fail_reason is None, second.fail_reason
    assert report.verdict is BenchmarkVerdict.PASS
    assert report.determinism.equivalent
    assert not report.determinism.mismatches
    assert report.determinism.normalization_rules
    first_fp = report.runs[0].fingerprint
    second_fp = report.runs[1].fingerprint
    assert first_fp.phase_sequence == second_fp.phase_sequence
    assert first_fp.generated_content_sha256 == second_fp.generated_content_sha256
    assert first_fp.plan_digest == second_fp.plan_digest
    assert first_fp.normalized_evidence_digest == second_fp.normalized_evidence_digest
    assert first_fp.repair_count == 1
    assert first.workflow_id != second.workflow_id
