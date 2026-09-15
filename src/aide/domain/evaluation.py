"""Deterministic Interview MVP evaluation contracts. Domain-only: no I/O or LLM judge."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.benchmark import MeasurementClass


class EvaluationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EvaluationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_TESTED = "NOT_TESTED"


class MvpReadiness(str, Enum):
    PRESENTABLE = "PRESENTABLE"
    PRESENTABLE_OFFLINE_CREDENTIAL_GATED = "PRESENTABLE_OFFLINE_CREDENTIAL_GATED"
    NOT_PRESENTABLE = "NOT_PRESENTABLE"


class EvaluationCategory(str, Enum):
    FUNCTIONAL_CORRECTNESS = "functional_correctness"
    REPAIR_CORRECTNESS = "repair_correctness"
    REPAIR_SAFETY = "repair_safety"
    POLICY_ENFORCEMENT = "policy_enforcement"
    LEAST_PRIVILEGE = "least_privilege"
    EVIDENCE_INTEGRITY = "evidence_integrity"
    DETERMINISM = "determinism"
    RECOVERY = "recovery"
    TEST_SUCCESS = "test_success"
    DATA_QUALITY = "data_quality"
    RECONCILIATION = "reconciliation"
    VERIFIER_CORRECTNESS = "verifier_correctness"
    PERFORMANCE = "performance"
    HUMAN_INTERVENTION_COUNT = "human_intervention_count"
    KNOWN_LIMITATIONS = "known_limitations"


class ScenarioResult(EvaluationModel):
    scenario_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: EvaluationCategory
    verdict: EvaluationVerdict
    evidence: str = Field(min_length=1)
    measurement: MeasurementClass = MeasurementClass.MEASURED
    notes: str = ""


class CategoryScore(EvaluationModel):
    category: EvaluationCategory
    verdict: EvaluationVerdict
    evidence: str
    scenario_ids: tuple[str, ...]
    measurement: MeasurementClass = MeasurementClass.MEASURED


class EvaluationReport(EvaluationModel):
    schema_version: int = Field(default=1, ge=1)
    task_id: str = Field(min_length=1)
    readiness: MvpReadiness
    categories: tuple[CategoryScore, ...]
    scenarios: tuple[ScenarioResult, ...]
    defects_found: tuple[str, ...]
    defects_fixed: tuple[str, ...]
    remaining_risks: tuple[str, ...]
    known_limitations: tuple[str, ...]
    benchmark_summary: str
    performance_summary: str


__all__ = [
    "CategoryScore",
    "EvaluationCategory",
    "EvaluationReport",
    "EvaluationVerdict",
    "MvpReadiness",
    "ScenarioResult",
]
