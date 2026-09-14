"""Deterministic Interview MVP quality assertions over built dbt relations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aide.capabilities.io import QualityCheckResult, ValidationReport

Execute = Callable[[str], Any]


def evaluate_interview_quality(
    execute: Execute,
    *,
    required_models: tuple[str, ...],
    schema: str = "AIDE_DEV",
) -> ValidationReport:
    checks: list[QualityCheckResult] = []
    missing: list[str] = []
    for name in required_models:
        present = _exists(execute, schema, name)
        if not present:
            missing.append(name)
        checks.append(
            QualityCheckResult(
                check_id=f"model_present:{name}",
                passed=present,
                detail="present" if present else "missing",
            )
        )
    mart = f'"{schema}"."mart_customer_revenue_daily"'
    lines = f'"{schema}"."fct_invoice_line"'
    try:
        row = execute(f"SELECT COUNT(*) FROM {mart}").fetchone()
        mart_count = int(row[0]) if row is not None else 0
    except Exception as exc:
        mart_count = 0
        checks.append(
            QualityCheckResult(
                check_id="mart_queryable",
                passed=False,
                detail=str(exc),
            )
        )
    else:
        checks.append(
            QualityCheckResult(
                check_id="mart_non_empty",
                passed=mart_count > 0,
                detail=f"rows={mart_count}",
            )
        )
    try:
        grain = execute(
            f"SELECT COUNT(*) FROM ("
            f"SELECT customer_sk, date_day FROM {mart} GROUP BY 1, 2 HAVING COUNT(*) > 1)"
        ).fetchone()
        grain_dupes = int(grain[0]) if grain is not None else 0
        checks.append(
            QualityCheckResult(
                check_id="mart_grain_unique",
                passed=grain_dupes == 0,
                detail=f"duplicate_groups={grain_dupes}",
            )
        )
    except Exception as exc:
        checks.append(
            QualityCheckResult(check_id="mart_grain_unique", passed=False, detail=str(exc))
        )
    try:
        recon = execute(
            f"SELECT abs("
            f"(SELECT coalesce(sum(invoiced_amount), 0) FROM {mart}) - "
            f"(SELECT coalesce(sum(amount), 0) FROM {lines})"
            f")"
        ).fetchone()
        delta = float(recon[0]) if recon is not None and recon[0] is not None else -1.0
        checks.append(
            QualityCheckResult(
                check_id="invoice_line_sum_matches_mart",
                passed=delta <= 0.01,
                detail=f"abs_delta={delta}",
            )
        )
    except Exception as exc:
        checks.append(
            QualityCheckResult(
                check_id="invoice_line_sum_matches_mart", passed=False, detail=str(exc)
            )
        )
    passed = all(item.passed for item in checks) and not missing
    return ValidationReport(
        passed=passed,
        checks=tuple(checks),
        row_count=mart_count,
        expected_columns=("customer_sk", "date_day", "invoiced_amount", "paid_amount"),
    )


def _exists(execute: Execute, schema: str, name: str) -> bool:
    try:
        execute(f'SELECT 1 FROM "{schema}"."{name}" LIMIT 0')
        return True
    except Exception:
        return False
