"""Deterministic Interview MVP quality assertions over built dbt relations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aide.capabilities.io import QualityCheckResult, ValidationReport

Execute = Callable[[str], Any]


def _relation(schema: str, name: str, *, quoted: bool) -> str:
    if quoted:
        return f'"{schema}"."{name}"'
    return f"{schema}.{name}"


def evaluate_interview_quality(
    execute: Execute,
    *,
    required_models: tuple[str, ...],
    schema: str = "AIDE_DEV",
    quoted_identifiers: bool = True,
) -> ValidationReport:
    checks: list[QualityCheckResult] = []
    missing: list[str] = []
    for name in required_models:
        present = _exists(execute, schema, name, quoted=quoted_identifiers)
        if not present:
            missing.append(name)
        checks.append(
            QualityCheckResult(
                check_id=f"model_present:{name}",
                passed=present,
                detail="present" if present else "missing",
            )
        )
    mart = _relation(schema, "mart_customer_revenue_daily", quoted=quoted_identifiers)
    lines = _relation(schema, "fct_invoice_line", quoted=quoted_identifiers)
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
            f"SELECT customer_sk, date_day, currency FROM {mart} "
            f"GROUP BY 1, 2, 3 HAVING COUNT(*) > 1)"
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
    _check_scalar(
        execute,
        checks,
        check_id="currency_isolated",
        sql=(
            f"SELECT COUNT(*) FROM {mart} "
            "WHERE currency IS NULL OR currency NOT IN ('EUR', 'USD', 'GBP')"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"non_canonical_rows={value}",
    )
    _check_scalar(
        execute,
        checks,
        check_id="net_paid_equals_paid_minus_refunded",
        sql=(
            f"SELECT COUNT(*) FROM {mart} "
            "WHERE abs(net_paid_amount - (paid_amount - refunded_amount)) > 0.01"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"mismatch_rows={value}",
    )
    _check_scalar(
        execute,
        checks,
        check_id="unknown_customer_preserved",
        sql=(
            f"SELECT COUNT(*) FROM {mart} "
            "WHERE customer_sk IS NULL "
            f"OR customer_sk NOT IN (SELECT customer_sk FROM "
            f"{_relation(schema, 'dim_customer', quoted=quoted_identifiers)})"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"unresolved_rows={value}",
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
    try:
        payments = _relation(schema, "fct_payment", quoted=quoted_identifiers)
        recon_pay = execute(
            f"SELECT abs("
            f"(SELECT coalesce(sum(paid_amount), 0) FROM {mart}) - "
            f"(SELECT coalesce(sum(amount), 0) FROM {payments})"
            f")"
        ).fetchone()
        pay_delta = (
            float(recon_pay[0]) if recon_pay is not None and recon_pay[0] is not None else -1.0
        )
        checks.append(
            QualityCheckResult(
                check_id="payment_sum_matches_mart",
                passed=pay_delta <= 0.01,
                detail=f"abs_delta={pay_delta}",
            )
        )
    except Exception as exc:
        checks.append(
            QualityCheckResult(check_id="payment_sum_matches_mart", passed=False, detail=str(exc))
        )
    invoices = _relation(schema, "stg_billing__invoices", quoted=quoted_identifiers)
    staged_lines = _relation(schema, "stg_billing__invoice_lines", quoted=quoted_identifiers)
    staged_payments = _relation(schema, "stg_payments__payments", quoted=quoted_identifiers)
    staged_refunds = _relation(schema, "stg_payments__refunds", quoted=quoted_identifiers)
    accounts = _relation(schema, "stg_crm__accounts", quoted=quoted_identifiers)
    deduped_customers = _relation(schema, "int_customer_deduplicated", quoted=quoted_identifiers)
    deduped_payments = _relation(schema, "int_payments_deduplicated", quoted=quoted_identifiers)
    _check_scalar(
        execute,
        checks,
        check_id="invoice_currency_matches_source_lines",
        sql=(
            "SELECT COUNT(*) FROM ("
            "SELECT coalesce(expected.currency, actual.currency) "
            "FROM ("
            f"SELECT invoices.currency AS currency, "
            f"sum(cast(lines.amount AS decimal(18, 2))) AS invoiced_amount "
            f"FROM {staged_lines} lines "
            f"INNER JOIN {invoices} invoices ON lines.invoice_id = invoices.invoice_id "
            "GROUP BY 1) expected "
            "FULL OUTER JOIN ("
            f"SELECT currency, sum(invoiced_amount) AS invoiced_amount FROM {mart} GROUP BY 1"
            ") actual ON expected.currency = actual.currency "
            "WHERE abs(coalesce(expected.invoiced_amount, 0) - "
            "coalesce(actual.invoiced_amount, 0)) > 0.01)"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"currency_mismatches={value}",
    )
    _check_scalar(
        execute,
        checks,
        check_id="paid_currency_matches_deduplicated_source",
        sql=(
            "SELECT COUNT(*) FROM ("
            "SELECT coalesce(expected.currency, actual.currency) "
            "FROM ("
            "SELECT invoices.currency AS currency, "
            "sum(cast(payments.amount AS decimal(18, 2))) AS paid_amount "
            "FROM ("
            "SELECT invoice_id, amount FROM ("
            "SELECT invoice_id, payment_ref, amount, "
            "row_number() OVER ("
            "PARTITION BY invoice_id, payment_ref "
            "ORDER BY _loaded_at DESC, payment_id) AS rn "
            f"FROM {staged_payments}) ranked WHERE rn = 1) payments "
            f"INNER JOIN {invoices} invoices ON payments.invoice_id = invoices.invoice_id "
            "GROUP BY 1) expected "
            "FULL OUTER JOIN ("
            f"SELECT currency, sum(paid_amount) AS paid_amount FROM {mart} GROUP BY 1"
            ") actual ON expected.currency = actual.currency "
            "WHERE abs(coalesce(expected.paid_amount, 0) - coalesce(actual.paid_amount, 0)) > 0.01)"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"currency_mismatches={value}",
    )
    _check_scalar(
        execute,
        checks,
        check_id="refund_currency_matches_source",
        sql=(
            "SELECT COUNT(*) FROM ("
            "SELECT coalesce(expected.currency, actual.currency) "
            "FROM ("
            "SELECT invoices.currency AS currency, "
            "sum(cast(refunds.amount AS decimal(18, 2))) AS refunded_amount "
            f"FROM {staged_refunds} refunds "
            f"INNER JOIN {staged_payments} payments ON refunds.payment_id = payments.payment_id "
            f"INNER JOIN {invoices} invoices ON payments.invoice_id = invoices.invoice_id "
            "GROUP BY 1) expected "
            "FULL OUTER JOIN ("
            f"SELECT currency, sum(refunded_amount) AS refunded_amount FROM {mart} GROUP BY 1"
            ") actual ON expected.currency = actual.currency "
            "WHERE abs(coalesce(expected.refunded_amount, 0) - "
            "coalesce(actual.refunded_amount, 0)) > 0.01)"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"currency_mismatches={value}",
    )
    _check_scalar(
        execute,
        checks,
        check_id="duplicate_payments_collapsed",
        sql=(
            "SELECT abs("
            f"(SELECT COUNT(*) FROM {deduped_payments}) - "
            f"(SELECT COUNT(*) FROM ("
            f"SELECT invoice_id, payment_ref FROM {staged_payments} GROUP BY 1, 2))"
            ")"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"survivor_delta={value}",
    )
    _check_scalar(
        execute,
        checks,
        check_id="deleted_crm_excluded",
        sql=(
            "SELECT COUNT(*) "
            f"FROM {deduped_customers} deduped "
            f"INNER JOIN {accounts} accounts ON deduped.account_id = accounts.account_id "
            "WHERE accounts.is_deleted"
        ),
        passed_when=lambda value: value == 0,
        detail=lambda value: f"deleted_survivors={value}",
    )
    passed = all(item.passed for item in checks) and not missing
    return ValidationReport(
        passed=passed,
        checks=tuple(checks),
        row_count=mart_count,
        expected_columns=(
            "customer_sk",
            "date_day",
            "currency",
            "invoiced_amount",
            "paid_amount",
            "refunded_amount",
            "net_paid_amount",
        ),
    )


def _check_scalar(
    execute: Execute,
    checks: list[QualityCheckResult],
    *,
    check_id: str,
    sql: str,
    passed_when: Callable[[int], bool],
    detail: Callable[[int], str],
) -> None:
    try:
        row = execute(sql).fetchone()
        value = int(row[0]) if row is not None and row[0] is not None else -1
        checks.append(
            QualityCheckResult(check_id=check_id, passed=passed_when(value), detail=detail(value))
        )
    except Exception as exc:
        checks.append(QualityCheckResult(check_id=check_id, passed=False, detail=str(exc)))


def _exists(execute: Execute, schema: str, name: str, *, quoted: bool = True) -> bool:
    try:
        execute(f"SELECT 1 FROM {_relation(schema, name, quoted=quoted)} LIMIT 0")
        return True
    except Exception:
        return False
