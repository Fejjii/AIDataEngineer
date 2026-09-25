"""Independent fixture oracle versus the generated customer-revenue mart."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import duckdb
import pytest

from aide.capabilities.io import GenerateTransformationInput
from aide.generation.validate import CONFIG_RE, REF_RE, SOURCE_RE, render_target_jinja
from aide.generation.vantara import generate_vantara_transformation
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.modelling.demo_design import vantara_model_design
from aide.quality.business_oracle import expect_business_correctness
from aide.quality.interview import evaluate_interview_quality

WORKFLOW = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
_REF_RE = re.compile(r"ref\(\s*'([^']+)'\s*\)")


def _build(version: str) -> duckdb.DuckDBPyConnection:
    generated = generate_vantara_transformation(
        GenerateTransformationInput(
            workflow_id=WORKFLOW,
            model_design=vantara_model_design(),
            fixture_version=version,  # type: ignore[arg-type]
        )
    )
    root = Path("synthetic/vantara/fixtures/tiny") / version / "csv"
    conn = duckdb.connect()
    conn.execute('CREATE SCHEMA "AIDE_DEV"')
    for schema, table in (
        ("crm", "accounts"),
        ("crm", "contacts"),
        ("crm", "account_crosswalk"),
        ("billing", "customers"),
        ("billing", "subscriptions"),
        ("billing", "invoices"),
        ("billing", "invoice_lines"),
        ("payments", "payments"),
        ("payments", "refunds"),
        ("product", "plans"),
    ):
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        conn.execute(
            f'CREATE TABLE "{schema}"."{table}" AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)',
            [str(root / schema / f"{table}.csv")],
        )
    files = {
        Path(item.path).stem: item.content for item in generated.files if item.path.endswith(".sql")
    }
    remaining = set(files)
    while remaining:
        ready = [
            name
            for name in sorted(remaining)
            if all(ref not in remaining for ref in _REF_RE.findall(files[name]))
        ]
        if not ready:
            raise RuntimeError(f"unresolved model cycle: {sorted(remaining)}")
        for name in ready:
            sql = render_target_jinja(files[name])
            sql = CONFIG_RE.sub("", sql)
            sql = SOURCE_RE.sub(lambda match: f'"{match.group(1)}"."{match.group(2)}"', sql)
            sql = REF_RE.sub(lambda match: f'"AIDE_DEV"."{match.group(1)}"', sql)
            conn.execute(f'CREATE TABLE "AIDE_DEV"."{name}" AS {sql}')
        remaining -= set(ready)
    return conn


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_mart_matches_fixture_oracle(version: str) -> None:
    expected = expect_business_correctness(version)
    conn = _build(version)
    try:
        rows = conn.execute(
            """
            SELECT customer_sk, cast(date_day AS varchar), currency,
                   invoiced_amount, paid_amount, refunded_amount, net_paid_amount
            FROM "AIDE_DEV"."mart_customer_revenue_daily"
            ORDER BY 1, 2, 3
            """
        ).fetchall()
        actual = [
            (
                row[0],
                row[1],
                row[2],
                _money(row[3]),
                _money(row[4]),
                _money(row[5]),
                _money(row[6]),
            )
            for row in rows
        ]
        oracle = [
            (
                row.customer_sk,
                row.date_day,
                row.currency,
                row.invoiced_amount.quantize(Decimal("0.01")),
                row.paid_amount.quantize(Decimal("0.01")),
                row.refunded_amount.quantize(Decimal("0.01")),
                row.net_paid_amount.quantize(Decimal("0.01")),
            )
            for row in expected.mart_rows
        ]
        assert actual == oracle
        deleted = conn.execute(
            """
            SELECT account_id
            FROM "AIDE_DEV"."int_customer_deduplicated"
            WHERE account_id IN (SELECT account_id FROM "crm"."accounts" WHERE is_deleted)
            """
        ).fetchall()
        assert deleted == []
        assert expected.deleted_accounts_in_survivors == ()
        fallback = conn.execute(
            """
            WITH linked AS (
              SELECT cast(customers.customer_id AS varchar) AS customer_id,
                     customers.customer_name,
                     coalesce(
                       cast(crosswalk.account_id AS varchar),
                       cast(customers.crm_account_id AS varchar)
                     ) AS account_id
              FROM "billing"."customers" customers
              LEFT JOIN "crm"."account_crosswalk" crosswalk
                ON cast(crosswalk.billing_customer_id AS varchar)
                 = cast(customers.customer_id AS varchar)
            )
            SELECT count(*)
            FROM linked
            LEFT JOIN "AIDE_DEV"."int_customer_deduplicated" deduped
              ON deduped.account_id = linked.account_id
            JOIN "AIDE_DEV"."dim_customer" dimension
              ON dimension.billing_customer_id = linked.customer_id
            WHERE deduped.account_id IS NULL
              AND (
                dimension.customer_name <> linked.customer_name
                OR dimension.website_domain IS NOT NULL
              )
            """
        ).fetchone()
        assert int(fallback[0]) == 0
        unknown = conn.execute(
            """
            SELECT count(DISTINCT invoice_id)
            FROM "AIDE_DEV"."fct_invoice_line"
            WHERE customer_sk = ?
            """,
            [expected.unknown_customer_sk],
        ).fetchone()
        assert int(unknown[0]) == expected.unknown_invoice_count
        null_customers = conn.execute(
            'SELECT count(*) FROM "AIDE_DEV"."mart_customer_revenue_daily" '
            "WHERE customer_sk IS NULL"
        ).fetchone()
        assert int(null_customers[0]) == 0
        line_rows = conn.execute(
            'SELECT count(*), count(DISTINCT invoice_line_id) FROM "AIDE_DEV"."fct_invoice_line"'
        ).fetchone()
        assert line_rows[0] == line_rows[1]
        report = evaluate_interview_quality(conn.execute, required_models=REQUIRED_DEMO_MODELS)
        failed = [(item.check_id, item.detail) for item in report.checks if not item.passed]
        assert report.passed, failed
    finally:
        conn.close()
