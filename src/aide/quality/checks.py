"""Deterministic quality checks. No LLM judge."""

from __future__ import annotations

from collections.abc import Sequence

from aide.capabilities.io import (
    ExecuteQueryOutput,
    ExpectedColumn,
    QualityCheckResult,
    ValidationReport,
)


def validate_query_result(
    result: ExecuteQueryOutput,
    *,
    expected_columns: Sequence[ExpectedColumn],
) -> ValidationReport:
    checks: list[QualityCheckResult] = []
    if result.rows is None:
        checks.append(
            QualityCheckResult(check_id="rows_present", passed=False, detail="no rows payload")
        )
    else:
        checks.append(
            QualityCheckResult(
                check_id="rows_present",
                passed=True,
                detail=f"{result.row_count} rows",
            )
        )
        observed = tuple(result.rows[0].keys()) if result.rows else ()
        expected_names = tuple(column.name for column in expected_columns)
        missing = [name for name in expected_names if name not in observed]
        checks.append(
            QualityCheckResult(
                check_id="expected_columns",
                passed=not missing,
                detail="ok" if not missing else f"missing {missing}",
            )
        )
        non_empty = result.row_count > 0
        checks.append(
            QualityCheckResult(
                check_id="non_empty",
                passed=non_empty,
                detail="aggregated investigation result is present",
            )
        )
    passed = all(item.passed for item in checks)
    return ValidationReport(
        passed=passed,
        checks=tuple(checks),
        row_count=result.row_count,
        expected_columns=tuple(column.name for column in expected_columns),
    )
