"""DuckDB fixture builder for offline fake connectors."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb

from synthetic.vantara.config import ProfileConfig
from synthetic.vantara.generate import GeneratedDataset
from synthetic.vantara.schema import SNOWFLAKE_DATABASE, TABLES, invoice_columns_for_version


def _create_table_sql(table_key: str, version: str) -> str:
    if table_key == "billing.invoices":
        columns = invoice_columns_for_version(version)
        table = TABLES["billing.invoices"]
    else:
        columns = TABLES[table_key].columns
        table = TABLES[table_key]
    col_defs = ", ".join(f'"{col.name}" {col.duckdb_type}' for col in columns)
    ident = f'"{SNOWFLAKE_DATABASE}"."{table.schema}"."{table.name}"'
    return f"CREATE TABLE {ident} ({col_defs})"


def export_duckdb_fixture(
    dataset: GeneratedDataset,
    config: ProfileConfig,
    version: str,
    output_path: Path,
    *,
    csv_dir: Path,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    conn = duckdb.connect(str(output_path))
    try:
        conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{SNOWFLAKE_DATABASE}"')
        for schema in ("CRM", "BILLING", "PAYMENTS", "PRODUCT", "SUPPORT"):
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{SNOWFLAKE_DATABASE}"."{schema}"')

        for table_key, table_def in TABLES.items():
            if table_key.startswith("billing.invoices"):
                continue
            conn.execute(_create_table_sql(table_key, version))
            csv_path = csv_dir / table_def.schema.lower() / f"{table_def.name.lower()}.csv"
            ident = f'"{SNOWFLAKE_DATABASE}"."{table_def.schema}"."{table_def.name}"'
            conn.execute(
                f"COPY {ident} FROM ? (HEADER, DELIMITER ',', QUOTE '\"', ESCAPE '\"')",
                [str(csv_path.resolve())],
            )

        conn.execute(_create_table_sql("billing.invoices", version))
        inv_csv = csv_dir / "billing" / "invoices.csv"
        inv_ident = f'"{SNOWFLAKE_DATABASE}"."BILLING"."INVOICES"'
        conn.execute(
            f"COPY {inv_ident} FROM ? (HEADER, DELIMITER ',', QUOTE '\"', ESCAPE '\"')",
            [str(inv_csv.resolve())],
        )
    finally:
        conn.close()
    return content_sha256(output_path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256(path: Path) -> str:
    """Deterministic hash of loaded table contents (not DuckDB file bytes)."""
    conn = duckdb.connect(str(path), read_only=True)
    digest = hashlib.sha256()
    try:
        table_keys = sorted(key for key in TABLES if not key.startswith("billing.invoices")) + [
            "billing.invoices"
        ]
        for table_key in table_keys:
            table = TABLES[table_key if table_key != "billing.invoices" else "billing.invoices"]
            ident = f'"{SNOWFLAKE_DATABASE}"."{table.schema}"."{table.name}"'
            fetched = conn.execute(
                f"SELECT COUNT(*) AS row_count, SUM(hash(COLUMNS(*))) AS row_hash FROM {ident}"
            ).fetchone()
            row_count = int(fetched[0]) if fetched is not None else 0
            row_hash = fetched[1] if fetched is not None else 0
            digest.update(f"{table_key}:{row_count}:{row_hash}".encode())
    finally:
        conn.close()
    return digest.hexdigest()


def verify_duckdb_integrity(path: Path, version: str) -> dict[str, int]:
    conn = duckdb.connect(str(path), read_only=True)
    try:
        counts: dict[str, int] = {}
        for table_key, table_def in TABLES.items():
            if table_key.startswith("billing.invoices"):
                continue
            ident = f'"{SNOWFLAKE_DATABASE}"."{table_def.schema}"."{table_def.name}"'
            result = conn.execute(f"SELECT COUNT(*) FROM {ident}").fetchone()
            counts[table_key] = int(result[0]) if result else 0
        inv_ident = f'"{SNOWFLAKE_DATABASE}"."BILLING"."INVOICES"'
        result = conn.execute(f"SELECT COUNT(*) FROM {inv_ident}").fetchone()
        counts["billing.invoices"] = int(result[0]) if result else 0
        status_col = "INVOICE_STATUS" if version == "v1" else "STATUS"
        pragma = f'PRAGMA table_info("{SNOWFLAKE_DATABASE}"."BILLING"."INVOICES")'
        cols = conn.execute(pragma).fetchall()
        col_names = {row[1] for row in cols}
        counts[f"has_{status_col.lower()}"] = int(status_col in col_names)
        return counts
    finally:
        conn.close()
