"""Snowflake loader script generation (not executed in Cloud)."""

from __future__ import annotations

from pathlib import Path

from synthetic.vantara.schema import SNOWFLAKE_DATABASE, TABLES


def render_snowflake_loader(profile: str) -> str:
    lines = [
        "-- Vantara synthetic Snowflake loader",
        "-- Profile: " + profile,
        "-- Execute locally with Snowflake credentials; not run in Cloud agents.",
        f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE};",
        f"USE DATABASE {SNOWFLAKE_DATABASE};",
    ]
    for schema in ("CRM", "BILLING", "PAYMENTS", "PRODUCT", "SUPPORT"):
        lines.append(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    for table_key, table_def in TABLES.items():
        if table_key.startswith("billing.invoices"):
            continue
        col_defs = ", ".join(
            f"{col.name} {col.duckdb_type.replace('DOUBLE', 'NUMBER(18,2)')}"
            for col in table_def.columns
        )
        lines.extend(
            [
                f"CREATE TABLE IF NOT EXISTS {table_def.schema}.{table_def.name} ({col_defs});",
                (
                    f"PUT file://fixtures/{profile}/v2/csv/{table_def.schema.lower()}/"
                    f"{table_def.name.lower()}.csv @%{table_def.schema}.{table_def.name};"
                ),
                (
                    f"COPY INTO {table_def.schema}.{table_def.name} "
                    f"FROM @%{table_def.schema}.{table_def.name} "
                    "FILE_FORMAT=(TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"');"
                ),
                "",
            ]
        )

    lines.extend(
        [
            "-- Invoices v2 uses STATUS column (post-drift).",
            "CREATE TABLE IF NOT EXISTS BILLING.INVOICES (",
            "  INVOICE_ID INTEGER, CUSTOMER_ID INTEGER, CURRENCY VARCHAR, ISSUE_DATE DATE,",
            "  DUE_DATE DATE, STATUS VARCHAR, TOTAL_AMOUNT NUMBER(18,2),",
            "  _LOADED_AT TIMESTAMP_NTZ, _EXTRACT_DATE DATE, _SOURCE_FILE VARCHAR",
            ");",
            f"PUT file://fixtures/{profile}/v2/csv/billing/invoices.csv @%BILLING.INVOICES;",
            "COPY INTO BILLING.INVOICES FROM @%BILLING.INVOICES "
            "FILE_FORMAT=(TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"');",
        ]
    )
    return "\n".join(lines)


def write_snowflake_loader(profile: str, output_root: Path) -> Path:
    scripts_dir = output_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / "load_snowflake.sql"
    path.write_text(render_snowflake_loader(profile), encoding="utf-8")
    return path
