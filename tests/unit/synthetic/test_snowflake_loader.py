from __future__ import annotations

import json
from pathlib import Path

from synthetic.vantara.config import DUPLICATE_PAYMENT_RATE
from synthetic.vantara.export.snowflake_export import (
    VALID_SNOWFLAKE_TYPES,
    render_snowflake_loader,
    snowflake_type,
    table_stage,
    write_snowflake_loader,
)
from synthetic.vantara.export.snowflake_load import expected_v2_row_counts
from synthetic.vantara.schema import TABLES, invoice_columns_for_version


def test_snowflake_types_are_valid_and_uuid_is_not_emitted() -> None:
    sql = render_snowflake_loader("tiny")
    assert " UUID," not in sql
    assert " UUID)" not in sql
    assert " UUID\n" not in sql
    assert "@VANTARA_RAW.CRM.%ACCOUNTS" in sql
    assert "@%CRM.ACCOUNTS" not in sql
    assert "STATUS VARCHAR" in sql
    assert "CREATE OR REPLACE TABLE CRM.ACCOUNTS" in sql
    assert "TIMESTAMP_FORMAT=" in sql
    assert "ON_ERROR='ABORT_STATEMENT'" in sql
    for table_key, table_def in TABLES.items():
        columns = (
            invoice_columns_for_version("v2")
            if table_key == "billing.invoices"
            else table_def.columns
        )
        for col in columns:
            mapped = snowflake_type(col.duckdb_type)
            assert mapped in VALID_SNOWFLAKE_TYPES
    assert snowflake_type("UUID") == "VARCHAR"
    assert snowflake_type("TIMESTAMP") == "TIMESTAMP_TZ"
    assert table_stage("BILLING", "INVOICES") == "@VANTARA_RAW.BILLING.%INVOICES"


def test_write_snowflake_loader_matches_renderer(tmp_path: Path) -> None:
    path = write_snowflake_loader("tiny", tmp_path)
    assert path.name == "load_snowflake.sql"
    text = path.read_text(encoding="utf-8")
    assert text == render_snowflake_loader("tiny")


def test_tiny_v2_csv_counts_match_generator_including_payment_redeliveries() -> None:
    csv_root = Path("synthetic/vantara/fixtures/tiny/v2/csv")
    expected = expected_v2_row_counts(csv_root)
    manifest = json.loads(
        Path("synthetic/vantara/expected/tiny/row_counts.json").read_text(encoding="utf-8")
    )
    grain = {key.upper(): count for key, count in manifest.items()}
    duplicates = max(1, round(grain["PAYMENTS.PAYMENTS"] * DUPLICATE_PAYMENT_RATE))
    v2_expected = dict(grain)
    v2_expected["PAYMENTS.PAYMENTS"] = grain["PAYMENTS.PAYMENTS"] + duplicates
    assert expected == v2_expected
    assert expected["PAYMENTS.PAYMENTS"] == 5735
    assert sum(expected.values()) == 35581
