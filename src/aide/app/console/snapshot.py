"""Bounded snapshot of one synthetic scenario execution.

Values come from the workflow that just ran. Nothing here is a canned expected row.
"""

from __future__ import annotations

import re
from typing import Any

from aide.app.benchmarking.summary import summarize_interview_demo
from aide.app.supervisor import InterviewResult
from aide.capabilities.io import RunTestsOutput
from aide.connectors.snowflake.masking import mask_row
from aide.domain.benchmark import (
    INTERVIEW_REQUEST,
    INTERVIEW_SCENARIO_ID,
    OPERATOR_BUSINESS_CORRECTNESS,
    OPERATOR_EXECUTION_LABEL,
    OPERATOR_LIMITATIONS,
    BenchmarkResult,
    BenchmarkRunRecord,
)
from aide.domain.repair import ACCEPTED_ARTIFACT_PATH
from aide.persistence.console import SNAPSHOT_ARTIFACT_TYPE

_SQL_PATH = re.compile(r"^models/(staging|intermediate|marts)/[A-Za-z0-9_]+\.sql$")
_MAX_SQL_FILES = 24
_MAX_SQL_CHARS = 8000
_MAX_TESTS = 40
_MAX_CELL = 80

# Version 2 adds benchmark metrics, evidence completeness, the Digital Twin summary,
# and per-workflow phase and outcome fields. Version 1 snapshots remain readable.
SNAPSHOT_SCHEMA_VERSION = 2
READABLE_SNAPSHOT_VERSIONS: frozenset[int] = frozenset({1, SNAPSHOT_SCHEMA_VERSION})

BUSINESS_CORRECTNESS = OPERATOR_BUSINESS_CORRECTNESS
EXECUTION_LABEL = OPERATOR_EXECUTION_LABEL
LIMITATIONS = OPERATOR_LIMITATIONS


def build_operator_snapshot(
    report: BenchmarkResult,
    first: InterviewResult,
    second: InterviewResult,
) -> dict[str, Any]:
    """Return a JSON-safe snapshot small enough to store as one artifact."""
    twin = summarize_interview_demo(report, first).digital_twin
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "artifact_type": SNAPSHOT_ARTIFACT_TYPE,
        "scenario_id": report.scenario_id or INTERVIEW_SCENARIO_ID,
        "business_objective": INTERVIEW_REQUEST,
        "execution_label": EXECUTION_LABEL,
        "business_correctness": BUSINESS_CORRECTNESS,
        "limitations": list(LIMITATIONS),
        "benchmark_verdict": report.verdict.value,
        "workflow_outcome": report.workflow_outcome,
        "determinism_equivalent": report.determinism.equivalent,
        "evidence_completeness_pct": report.evidence_completeness.completeness_pct,
        "evidence_complete": report.evidence_completeness.complete,
        "evidence_completeness": report.evidence_completeness.model_dump(mode="json"),
        "metrics": report.value_metrics.model_dump(mode="json"),
        "digital_twin": twin.model_dump(mode="json"),
        "workflows": [
            _workflow_snapshot(first, report.runs[0]),
            _workflow_snapshot(second, report.runs[1]),
        ],
    }


def _workflow_snapshot(result: InterviewResult, record: BenchmarkRunRecord) -> dict[str, Any]:
    preview = result.extra.get("output_preview")
    return {
        "workflow_id": str(result.workflow_id),
        "benchmark_outcome": record.workflow_outcome,
        "fail_reason": result.fail_reason,
        "block_reason": result.block_reason,
        "phase_sequence": list(result.workflow_states),
        "repair_class": record.repair_class,
        "repair_count": record.repair_count,
        "test_outcome": record.test_outcome,
        "quality_outcome": record.quality_outcome,
        "reconciliation_outcome": record.reconciliation_outcome,
        "verifier_verdict": (
            record.verifier_verdict.value if record.verifier_verdict is not None else None
        ),
        "tests_executed": record.tests_executed,
        "quality_checks_executed": record.quality_checks_executed,
        "governed_tool_operations": record.governed_tool_operations,
        "policy_evaluations": record.policy_evaluations,
        "wall_clock_duration_ms": record.wall_clock_duration_ms,
        "models": _model_files(result),
        "original_sql": _original_sql(result),
        "individual_tests": _tests(result),
        "output_preview": _preview(preview) if isinstance(preview, dict) else None,
    }


def _model_files(result: InterviewResult) -> list[dict[str, str]]:
    generated = result.generated
    if generated is None:
        return []
    files: list[dict[str, str]] = []
    for item in generated.files:
        if item.kind != "MODEL_SQL" or _SQL_PATH.fullmatch(item.path) is None:
            continue
        sql = item.content.strip()
        if len(sql) > _MAX_SQL_CHARS:
            sql = sql[:_MAX_SQL_CHARS] + "\n-- truncated for display"
        files.append({"path": item.path, "sql": sql})
        if len(files) >= _MAX_SQL_FILES:
            break
    return files


def _original_sql(result: InterviewResult) -> str | None:
    generated = result.generated
    if generated is None:
        return None
    for item in generated.files:
        if item.path == ACCEPTED_ARTIFACT_PATH and _SQL_PATH.fullmatch(item.path):
            sql = item.content.strip()
            if len(sql) > _MAX_SQL_CHARS:
                return sql[:_MAX_SQL_CHARS] + "\n-- truncated for display"
            return sql
    return None


def _tests(result: InterviewResult) -> list[dict[str, Any]]:
    last = result.extra.get("last_tests")
    if not isinstance(last, RunTestsOutput):
        return []
    rows: list[dict[str, Any]] = []
    for item in last.tests[:_MAX_TESTS]:
        rows.append(
            {
                "test_name": item.test_name,
                "model": item.model,
                "column": item.column,
                "status": item.status,
                "failures": item.failures,
            }
        )
    return rows


def _preview(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("relation") != "AIDE_DEV.mart_customer_revenue_daily":
        return None
    columns = raw.get("columns")
    rows = raw.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None
    kept = [str(name) for name in columns[:12]]
    masked_rows: list[dict[str, Any]] = []
    for row in rows[:20]:
        if not isinstance(row, dict):
            continue
        limited = {name: row.get(name) for name in kept}
        masked = mask_row(limited, sensitive=set())
        masked_rows.append({key: _cell(value) for key, value in masked.items()})
    total = raw.get("total_row_count")
    return {
        "relation": "AIDE_DEV.mart_customer_revenue_daily",
        "columns": kept,
        "rows": masked_rows,
        "sampled_row_count": len(masked_rows),
        "total_row_count": total if isinstance(total, int) else None,
        "truncated": bool(raw.get("truncated")),
        "note": (
            "Bounded sample from the executed mart. Amounts are synthetic, "
            "separated by currency, and are not production financial revenue."
        ),
    }


def _cell(value: object) -> object:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return None
        return value
    text = str(value)
    if len(text) > _MAX_CELL:
        return text[:_MAX_CELL]
    return text


def public_failure_message(exc: BaseException) -> str:
    """Short operator-facing failure text. Drops lines that look like secrets."""
    name = type(exc).__name__
    line = str(exc).splitlines()[0] if str(exc) else ""
    lowered = line.lower()
    if any(token in lowered for token in ("password", "secret", "token", "private_key")):
        line = ""
    line = line[:240]
    if line:
        return f"{name}: {line}"[:300]
    return name


def failure_messages(body: dict[str, Any] | None) -> tuple[str, ...]:
    """Error strings from a persisted original_failure artifact. Empty when absent."""
    if not isinstance(body, dict):
        return ()
    results = body.get("results")
    if not isinstance(results, list):
        return ()
    messages: list[str] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "error":
            continue
        message = item.get("message")
        model = item.get("model") or item.get("name") or "model"
        text = str(message or "error")
        messages.append(f"{model}: {text}")
    return tuple(messages)


__all__ = [
    "BUSINESS_CORRECTNESS",
    "EXECUTION_LABEL",
    "LIMITATIONS",
    "READABLE_SNAPSHOT_VERSIONS",
    "SNAPSHOT_SCHEMA_VERSION",
    "build_operator_snapshot",
    "failure_messages",
    "public_failure_message",
]
