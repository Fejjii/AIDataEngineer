"""Vantara tiny-fixture identity and DuckDB table installation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from synthetic.vantara.config import PACKAGE_ROOT
from synthetic.vantara.schema import (
    SNOWFLAKE_DATABASE,
    TABLES,
    ColumnDef,
    invoice_columns_for_version,
)

from aide.domain.sql import AssetKind, AssetRef

CONNECTOR_ID = "snowflake_ro"
PII_COLUMNS_PATH = PACKAGE_ROOT / "pii_columns.yaml"
TINY_FIXTURE_ROOT = PACKAGE_ROOT / "fixtures" / "tiny"

DEMO_SELECTED_ADDRESSES: tuple[tuple[str, str, str], ...] = (
    (SNOWFLAKE_DATABASE, "CRM", "ACCOUNTS"),
    (SNOWFLAKE_DATABASE, "CRM", "CONTACTS"),
    (SNOWFLAKE_DATABASE, "CRM", "ACCOUNT_CROSSWALK"),
    (SNOWFLAKE_DATABASE, "BILLING", "CUSTOMERS"),
    (SNOWFLAKE_DATABASE, "BILLING", "SUBSCRIPTIONS"),
    (SNOWFLAKE_DATABASE, "BILLING", "INVOICES"),
    (SNOWFLAKE_DATABASE, "BILLING", "INVOICE_LINES"),
    (SNOWFLAKE_DATABASE, "PAYMENTS", "PAYMENTS"),
    (SNOWFLAKE_DATABASE, "PAYMENTS", "REFUNDS"),
    (SNOWFLAKE_DATABASE, "PRODUCT", "PLANS"),
)

EXCLUDED_DEMO_ADDRESSES: tuple[tuple[str, str, str], ...] = (
    (SNOWFLAKE_DATABASE, "CRM", "OPPORTUNITIES"),
    (SNOWFLAKE_DATABASE, "SUPPORT", "TICKETS"),
)

SAMPLE_PRIORITY_ADDRESSES: tuple[tuple[str, str, str], ...] = (
    (SNOWFLAKE_DATABASE, "CRM", "ACCOUNTS"),
    (SNOWFLAKE_DATABASE, "CRM", "CONTACTS"),
    (SNOWFLAKE_DATABASE, "PAYMENTS", "PAYMENTS"),
)

type AssetAddress = tuple[str, str, str]
type RelationshipPair = tuple[AssetAddress, str, AssetAddress, str]
# Evaluation / test baseline only. Production inference must not import this list.
KNOWN_RELATIONSHIP_PAIRS: tuple[RelationshipPair, ...] = (
    (
        (SNOWFLAKE_DATABASE, "BILLING", "CUSTOMERS"),
        "CRM_ACCOUNT_ID",
        (SNOWFLAKE_DATABASE, "CRM", "ACCOUNTS"),
        "ACCOUNT_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "CRM", "CONTACTS"),
        "ACCOUNT_ID",
        (SNOWFLAKE_DATABASE, "CRM", "ACCOUNTS"),
        "ACCOUNT_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "CRM", "ACCOUNT_CROSSWALK"),
        "ACCOUNT_ID",
        (SNOWFLAKE_DATABASE, "CRM", "ACCOUNTS"),
        "ACCOUNT_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "CRM", "ACCOUNT_CROSSWALK"),
        "BILLING_CUSTOMER_ID",
        (SNOWFLAKE_DATABASE, "BILLING", "CUSTOMERS"),
        "CUSTOMER_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "BILLING", "CUSTOMERS"),
        "CUSTOMER_ID",
        (SNOWFLAKE_DATABASE, "CRM", "ACCOUNT_CROSSWALK"),
        "BILLING_CUSTOMER_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "BILLING", "INVOICES"),
        "CUSTOMER_ID",
        (SNOWFLAKE_DATABASE, "BILLING", "CUSTOMERS"),
        "CUSTOMER_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "BILLING", "INVOICE_LINES"),
        "INVOICE_ID",
        (SNOWFLAKE_DATABASE, "BILLING", "INVOICES"),
        "INVOICE_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "BILLING", "INVOICE_LINES"),
        "PLAN_CODE",
        (SNOWFLAKE_DATABASE, "PRODUCT", "PLANS"),
        "PLAN_CODE",
    ),
    (
        (SNOWFLAKE_DATABASE, "BILLING", "SUBSCRIPTIONS"),
        "CUSTOMER_ID",
        (SNOWFLAKE_DATABASE, "BILLING", "CUSTOMERS"),
        "CUSTOMER_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "BILLING", "SUBSCRIPTIONS"),
        "PLAN_CODE",
        (SNOWFLAKE_DATABASE, "PRODUCT", "PLANS"),
        "PLAN_CODE",
    ),
    (
        (SNOWFLAKE_DATABASE, "PAYMENTS", "PAYMENTS"),
        "INVOICE_ID",
        (SNOWFLAKE_DATABASE, "BILLING", "INVOICES"),
        "INVOICE_ID",
    ),
    (
        (SNOWFLAKE_DATABASE, "PAYMENTS", "REFUNDS"),
        "PAYMENT_ID",
        (SNOWFLAKE_DATABASE, "PAYMENTS", "PAYMENTS"),
        "PAYMENT_ID",
    ),
)


def demo_selected_assets(connector_id: str = CONNECTOR_ID) -> tuple[AssetRef, ...]:
    return tuple(
        AssetRef(
            connector_id=connector_id,
            address=address,
            kind=AssetKind.TABLE,
            platform_type="snowflake",
        )
        for address in DEMO_SELECTED_ADDRESSES
    )


def asset_slug(asset: AssetRef) -> str:
    return "_".join(part.lower() for part in asset.address)


def table_key(address: tuple[str, ...]) -> str:
    return f"{address[1].lower()}.{address[2].lower()}"


def columns_for(address: tuple[str, ...], version: str) -> tuple[ColumnDef, ...]:
    key = table_key(address)
    if key == "billing.invoices":
        return invoice_columns_for_version(version)
    table = TABLES[key]
    return table.columns


def grain_columns(address: tuple[str, ...]) -> tuple[str, ...]:
    key = table_key(address)
    if key not in TABLES:
        return ()
    return tuple(part.strip() for part in TABLES[key].grain.split(",") if part.strip())


def csv_path(address: tuple[str, ...], version: str) -> Path:
    schema = address[1].lower()
    table = address[2].lower()
    return TINY_FIXTURE_ROOT / version / "csv" / schema / f"{table}.csv"


def load_pii_columns(path: Path | None = None) -> frozenset[str]:
    text = (path or PII_COLUMNS_PATH).read_text(encoding="utf-8")
    names: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("column:"):
            names.add(stripped.split(":", 1)[1].strip().upper())
    return frozenset(names)


def duckdb_type(column: ColumnDef) -> str:
    if column.duckdb_type == "UUID":
        return "VARCHAR"
    if column.duckdb_type.startswith("VARCHAR"):
        return "VARCHAR"
    return column.duckdb_type


def flattened_ident(address: tuple[str, ...]) -> str:
    return ".".join(part.upper() for part in address)


def install_vantara_tables(conn: Any, version: str) -> None:
    """Load committed tiny CSVs into flattened DuckDB names used by the fake connector."""
    if version not in {"v1", "v2"}:
        raise ValueError("fixture version must be v1 or v2")
    for address in tuple(item[0:3] for item in DEMO_SELECTED_ADDRESSES) + EXCLUDED_DEMO_ADDRESSES:
        ident = flattened_ident(address)
        columns = columns_for(address, version)
        col_sql = ", ".join(f'"{col.name}" {duckdb_type(col)}' for col in columns)
        conn.execute(f'DROP TABLE IF EXISTS "{ident}"')
        conn.execute(f'CREATE TABLE "{ident}" ({col_sql})')
        source = csv_path(address, version)
        conn.execute(
            f"""
            COPY "{ident}" FROM ? (HEADER, DELIMITER ',', QUOTE '"', ESCAPE '"')
            """,
            [str(source.resolve())],
        )
