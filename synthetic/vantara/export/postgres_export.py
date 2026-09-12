"""PostgreSQL DDL and load script generation."""

from __future__ import annotations

from pathlib import Path

from synthetic.vantara.config import ProfileConfig
from synthetic.vantara.schema import TABLES, invoice_columns_for_version


def render_postgres_ddl(version: str) -> str:
    lines = [
        "-- Vantara synthetic source PostgreSQL DDL",
        "CREATE SCHEMA IF NOT EXISTS vantara_crm;",
        "CREATE SCHEMA IF NOT EXISTS vantara_billing;",
        "CREATE SCHEMA IF NOT EXISTS vantara_payments;",
        "CREATE SCHEMA IF NOT EXISTS vantara_product;",
        "CREATE SCHEMA IF NOT EXISTS vantara_support;",
        "",
    ]
    schema_map = {
        "CRM": "vantara_crm",
        "BILLING": "vantara_billing",
        "PAYMENTS": "vantara_payments",
        "PRODUCT": "vantara_product",
        "SUPPORT": "vantara_support",
    }
    for table_key, table_def in TABLES.items():
        if table_key.startswith("billing.invoices"):
            continue
        pg_schema = schema_map[table_def.schema]
        columns = table_def.columns
        if table_key == "billing.invoices":
            columns = invoice_columns_for_version(version)
        col_sql = ",\n  ".join(
            f"{col.name} {col.pg_type}{'' if col.nullable else ' NOT NULL'}" for col in columns
        )
        lines.extend(
            [
                f"DROP TABLE IF EXISTS {pg_schema}.{table_def.name.lower()};",
                f"CREATE TABLE {pg_schema}.{table_def.name.lower()} (",
                f"  {col_sql}",
                ");",
                "",
            ]
        )
    inv_cols = invoice_columns_for_version(version)
    col_sql = ",\n  ".join(
        f"{col.name} {col.pg_type}{'' if col.nullable else ' NOT NULL'}" for col in inv_cols
    )
    lines.extend(
        [
            "DROP TABLE IF EXISTS vantara_billing.invoices;",
            "CREATE TABLE vantara_billing.invoices (",
            f"  {col_sql}",
            ");",
            "",
        ]
    )
    return "\n".join(lines)


def render_postgres_load_script(profile: str, version: str) -> str:
    return f"""#!/usr/bin/env bash
# Load Vantara synthetic CSV fixtures into PostgreSQL (profile={profile}, version={version})
set -euo pipefail
ROOT="$(cd "$(dirname "${{BASH_SOURCE[0]}}")/.." && pwd)"
CSV_ROOT="${{ROOT}}/fixtures/{profile}/{version}/csv"
PSQL="${{PSQL:-psql}}"

psql "${{DATABASE_URL:?DATABASE_URL is required}}" -f "${{ROOT}}/postgres/ddl_{version}.sql"

copy_table() {{
  local schema="$1" table="$2" file="$3"
  ${{PSQL}} "${{DATABASE_URL}}" -c \\
    "\\copy ${{schema}}.${{table}} FROM '${{CSV_ROOT}}/${{file}}' CSV HEADER"
}}

copy_table vantara_crm accounts crm/accounts.csv
copy_table vantara_crm contacts crm/contacts.csv
copy_table vantara_crm opportunities crm/opportunities.csv
copy_table vantara_crm account_crosswalk crm/account_crosswalk.csv
copy_table vantara_billing customers billing/customers.csv
copy_table vantara_billing subscriptions billing/subscriptions.csv
copy_table vantara_billing invoices billing/invoices.csv
copy_table vantara_billing invoice_lines billing/invoice_lines.csv
copy_table vantara_payments payments payments/payments.csv
copy_table vantara_payments refunds payments/refunds.csv
copy_table vantara_product plans product/plans.csv
copy_table vantara_support tickets support/tickets.csv
"""


def write_postgres_artifacts(config: ProfileConfig, version: str, output_root: Path) -> None:
    postgres_dir = output_root / "postgres"
    postgres_dir.mkdir(parents=True, exist_ok=True)
    (postgres_dir / f"ddl_{version}.sql").write_text(render_postgres_ddl(version), encoding="utf-8")
    load_path = postgres_dir / f"load_{version}.sh"
    load_path.write_text(
        render_postgres_load_script(config.profile.value, version),
        encoding="utf-8",
    )
    load_path.chmod(0o755)
