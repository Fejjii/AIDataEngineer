"""Snowflake loader script generation (not executed in Cloud)."""

from __future__ import annotations

from pathlib import Path

from synthetic.vantara.schema import (
    SNOWFLAKE_DATABASE,
    TABLES,
    ColumnDef,
    invoice_columns_for_version,
)

# DuckDB generator types → valid Snowflake types. UUID is not a Snowflake type.
_SNOWFLAKE_TYPE = {
    "UUID": "VARCHAR",
    "TIMESTAMP": "TIMESTAMP_TZ",
    "DOUBLE": "NUMBER(18,2)",
    "VARCHAR": "VARCHAR",
    "BOOLEAN": "BOOLEAN",
    "DATE": "DATE",
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
}

VALID_SNOWFLAKE_TYPES = frozenset(
    {
        "VARCHAR",
        "TIMESTAMP_TZ",
        "TIMESTAMP_NTZ",
        "BOOLEAN",
        "DATE",
        "INTEGER",
        "BIGINT",
        "NUMBER(18,2)",
    }
)

SCHEMAS = ("CRM", "BILLING", "PAYMENTS", "PRODUCT", "SUPPORT")

COPY_FILE_FORMAT = (
    "TYPE=CSV SKIP_HEADER=1 FIELD_OPTIONALLY_ENCLOSED_BY='\"' "
    "EMPTY_FIELD_AS_NULL=TRUE TRIM_SPACE=TRUE DATE_FORMAT='YYYY-MM-DD' "
    "TIMESTAMP_FORMAT='YYYY-MM-DD\"T\"HH24:MI:SSTZH:TZM'"
)


def snowflake_type(duckdb_type: str) -> str:
    """Map a generator/DuckDB type onto a real Snowflake type. Fail closed on unknowns."""
    if duckdb_type.startswith("NUMBER(") and duckdb_type in VALID_SNOWFLAKE_TYPES:
        return duckdb_type
    mapped = _SNOWFLAKE_TYPE.get(duckdb_type)
    if mapped is None or mapped not in VALID_SNOWFLAKE_TYPES:
        raise ValueError(f"unsupported Snowflake type mapping for {duckdb_type!r}")
    return mapped


def table_stage(schema: str, name: str) -> str:
    """Fully qualified table stage: @DB.SCHEMA.%TABLE."""
    return f"@{SNOWFLAKE_DATABASE}.{schema}.%{name}"


def columns_for_v2(table_key: str, table_columns: tuple[ColumnDef, ...]) -> tuple[ColumnDef, ...]:
    if table_key == "billing.invoices":
        return invoice_columns_for_version("v2")
    return table_columns


def csv_relative_path(schema: str, name: str) -> str:
    return f"{schema.lower()}/{name.lower()}.csv"


def render_snowflake_loader(profile: str) -> str:
    lines = [
        "-- Vantara synthetic Snowflake loader",
        "-- Profile: " + profile,
        "-- Execute locally with Snowflake credentials; not run in Cloud agents.",
        "-- Unique-id generator columns use VARCHAR. Table stages are @DB.SCHEMA.%TABLE.",
        "-- Prefer: uv run aide demo load-snowflake --profile tiny",
        "-- CREATE DATABASE/SCHEMA are optional; the Python loader does not require those grants.",
        f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE};",
        f"USE DATABASE {SNOWFLAKE_DATABASE};",
    ]
    for schema in SCHEMAS:
        lines.append(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    for table_key, table_def in TABLES.items():
        columns = columns_for_v2(table_key, table_def.columns)
        col_defs = ", ".join(f"{col.name} {snowflake_type(col.duckdb_type)}" for col in columns)
        stage = table_stage(table_def.schema, table_def.name)
        rel = csv_relative_path(table_def.schema, table_def.name)
        lines.extend(
            [
                f"CREATE OR REPLACE TABLE {table_def.schema}.{table_def.name} ({col_defs});",
                (
                    f"PUT file://fixtures/{profile}/v2/csv/{rel} {stage} "
                    "AUTO_COMPRESS=FALSE OVERWRITE=TRUE;"
                ),
                (
                    f"COPY INTO {table_def.schema}.{table_def.name} FROM {stage} "
                    f"FILE_FORMAT=({COPY_FILE_FORMAT}) ON_ERROR='ABORT_STATEMENT';"
                ),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_snowflake_loader(profile: str, output_root: Path) -> Path:
    scripts_dir = output_root / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    path = scripts_dir / "load_snowflake.sql"
    path.write_text(render_snowflake_loader(profile), encoding="utf-8")
    return path
