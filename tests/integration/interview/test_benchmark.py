from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.runner import run_offline_benchmark
from aide.app.supervisor import LEGAL_INTERVIEW_PHASES
from aide.connectors.snowflake.manifest import tiny_manifest_digest
from aide.domain.benchmark import BenchmarkVerdict, MeasurementClass
from aide.domain.states import WorkflowState
from aide.domain.verification import REQUIRED_EVIDENCE_SECTIONS, VerifierVerdict
from aide.modelling.constants import REQUIRED_DEMO_MODELS


@pytest.mark.asyncio
async def test_at23_offline_scenario_runs_twice_with_equivalent_fingerprints(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    report, first, second = await run_offline_benchmark(session_factory, tmp_path)
    first_fp = report.runs[0].fingerprint
    second_fp = report.runs[1].fingerprint
    assert first.fail_reason is None, first.fail_reason
    assert second.fail_reason is None, second.fail_reason
    assert first.verifier is not None and first.verifier.verdict is VerifierVerdict.PASS
    assert second.verifier is not None and second.verifier.verdict is VerifierVerdict.PASS
    assert report.verdict is BenchmarkVerdict.PASS
    assert report.determinism.equivalent
    assert not report.determinism.mismatches
    expected_phases = [phase.value for phase in LEGAL_INTERVIEW_PHASES] + [
        WorkflowState.REPAIR.value,
        WorkflowState.EXECUTION.value,
        WorkflowState.VALIDATION.value,
    ]
    assert list(first.workflow_states) == expected_phases
    assert first_fp.phase_sequence == second_fp.phase_sequence
    assert first_fp.model_names == second_fp.model_names
    assert first.generated is not None
    assert set(REQUIRED_DEMO_MODELS).issubset(set(first.generated.model_names or ()))
    assert first_fp.generated_content_sha256 == second_fp.generated_content_sha256
    assert first_fp.plan_digest == second_fp.plan_digest
    assert first_fp.repair_class == "SCHEMA_MISMATCH"
    assert first_fp.repair_count == 1
    assert first_fp.before_artifact_hash == second_fp.before_artifact_hash
    assert first_fp.after_artifact_hash == second_fp.after_artifact_hash
    assert first_fp.normalized_evidence_digest == second_fp.normalized_evidence_digest
    assert first.workflow_id != second.workflow_id
    assert report.runs[0].evidence_bundle_sha256 != report.runs[1].evidence_bundle_sha256
    assert report.evidence_completeness.complete
    assert report.evidence_completeness.completeness_pct == 100
    assert not report.evidence_completeness.missing_sections
    assert not report.evidence_completeness.digest_mismatches
    assert set(REQUIRED_EVIDENCE_SECTIONS).issubset(set(first.extra.get("typed_evidence", {})))
    loaded = first.extra.get("manifest_load")
    assert loaded is not None
    assert loaded.fixture_digest == tiny_manifest_digest()
    assert loaded.reconcile_ok
    classifications = {item.name: item.classification for item in report.runs[0].measurements}
    assert classifications["wall_clock_duration_ms"] is MeasurementClass.MEASURED
    assert classifications["model_tokens"] is MeasurementClass.UNAVAILABLE
    assert classifications["warehouse_credits"] is MeasurementClass.UNAVAILABLE
    assert classifications["model_cost_usd"] is MeasurementClass.UNAVAILABLE
    assert report.scorecard
    assert report.value_metrics.automatic_repairs == 1
    assert report.value_metrics.human_interventions == 0
    assert report.value_metrics.estimated_engineering_steps_automated == 9
    assert "workflow_id" in report.determinism.variable_fields
    assert report.determinism.normalization_rules
    assert first.extra.get("step_durations_ms")
    assert int(first.extra.get("repair_duration_ms", 0)) >= 0
    assert first_fp.capability_sequence
    assert first_fp.capability_sequence == second_fp.capability_sequence
