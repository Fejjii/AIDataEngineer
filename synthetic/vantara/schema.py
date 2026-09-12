"""Table and column definitions for Vantara synthetic sources."""

from __future__ import annotations

from dataclasses import dataclass

SNOWFLAKE_DATABASE = "VANTARA_RAW"


@dataclass(frozen=True, slots=True)
class ColumnDef:
    name: str
    pg_type: str
    duckdb_type: str
    nullable: bool = True


@dataclass(frozen=True, slots=True)
class TableDef:
    schema: str
    name: str
    columns: tuple[ColumnDef, ...]
    grain: str

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def snowflake_ident(self) -> str:
        return f"{SNOWFLAKE_DATABASE}.{self.schema}.{self.name}"


METADATA_COLUMNS: tuple[ColumnDef, ...] = (
    ColumnDef("_LOADED_AT", "TIMESTAMP", "TIMESTAMP", False),
    ColumnDef("_EXTRACT_DATE", "DATE", "DATE", False),
    ColumnDef("_SOURCE_FILE", "VARCHAR(512)", "VARCHAR", False),
)


TABLES: dict[str, TableDef] = {
    "crm.accounts": TableDef(
        "CRM",
        "ACCOUNTS",
        (
            ColumnDef("ACCOUNT_ID", "UUID", "UUID", False),
            ColumnDef("ACCOUNT_NAME", "VARCHAR(256)", "VARCHAR", False),
            ColumnDef("WEBSITE_DOMAIN", "VARCHAR(256)", "VARCHAR", True),
            ColumnDef("INDUSTRY", "VARCHAR(128)", "VARCHAR", True),
            ColumnDef("COUNTRY", "VARCHAR(128)", "VARCHAR", True),
            ColumnDef("OWNER_ID", "UUID", "UUID", True),
            ColumnDef("CREATED_AT", "TIMESTAMP", "TIMESTAMP", False),
            ColumnDef("UPDATED_AT", "TIMESTAMP", "TIMESTAMP", False),
            ColumnDef("IS_DELETED", "BOOLEAN", "BOOLEAN", False),
        )
        + METADATA_COLUMNS,
        "ACCOUNT_ID",
    ),
    "crm.contacts": TableDef(
        "CRM",
        "CONTACTS",
        (
            ColumnDef("CONTACT_ID", "UUID", "UUID", False),
            ColumnDef("ACCOUNT_ID", "UUID", "UUID", True),
            ColumnDef("FIRST_NAME", "VARCHAR(128)", "VARCHAR", False),
            ColumnDef("LAST_NAME", "VARCHAR(128)", "VARCHAR", False),
            ColumnDef("EMAIL", "VARCHAR(256)", "VARCHAR", True),
            ColumnDef("PHONE", "VARCHAR(64)", "VARCHAR", True),
            ColumnDef("CREATED_AT", "TIMESTAMP", "TIMESTAMP", False),
            ColumnDef("UPDATED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "CONTACT_ID",
    ),
    "crm.opportunities": TableDef(
        "CRM",
        "OPPORTUNITIES",
        (
            ColumnDef("OPPORTUNITY_ID", "UUID", "UUID", False),
            ColumnDef("ACCOUNT_ID", "UUID", "UUID", False),
            ColumnDef("STAGE", "VARCHAR(64)", "VARCHAR", False),
            ColumnDef("AMOUNT", "NUMERIC(18,2)", "DOUBLE", True),
            ColumnDef("CREATED_AT", "TIMESTAMP", "TIMESTAMP", False),
            ColumnDef("UPDATED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "OPPORTUNITY_ID",
    ),
    "crm.account_crosswalk": TableDef(
        "CRM",
        "ACCOUNT_CROSSWALK",
        (
            ColumnDef("ACCOUNT_ID", "UUID", "UUID", False),
            ColumnDef("BILLING_CUSTOMER_ID", "INTEGER", "INTEGER", False),
            ColumnDef("CREATED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "ACCOUNT_ID,BILLING_CUSTOMER_ID",
    ),
    "billing.customers": TableDef(
        "BILLING",
        "CUSTOMERS",
        (
            ColumnDef("CUSTOMER_ID", "INTEGER", "INTEGER", False),
            ColumnDef("CUSTOMER_NAME", "VARCHAR(256)", "VARCHAR", False),
            ColumnDef("CRM_ACCOUNT_ID", "UUID", "UUID", True),
            ColumnDef("BILLING_COUNTRY", "VARCHAR(2)", "VARCHAR", True),
            ColumnDef("CREATED_AT", "TIMESTAMP", "TIMESTAMP", False),
            ColumnDef("UPDATED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "CUSTOMER_ID",
    ),
    "billing.subscriptions": TableDef(
        "BILLING",
        "SUBSCRIPTIONS",
        (
            ColumnDef("SUBSCRIPTION_ID", "INTEGER", "INTEGER", False),
            ColumnDef("CUSTOMER_ID", "INTEGER", "INTEGER", False),
            ColumnDef("PLAN_CODE", "VARCHAR(64)", "VARCHAR", False),
            ColumnDef("STATUS", "VARCHAR(32)", "VARCHAR", False),
            ColumnDef("START_DATE", "DATE", "DATE", False),
            ColumnDef("END_DATE", "DATE", "DATE", True),
            ColumnDef("UPDATED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "SUBSCRIPTION_ID",
    ),
    "billing.invoices": TableDef(
        "BILLING",
        "INVOICES",
        (
            ColumnDef("INVOICE_ID", "INTEGER", "INTEGER", False),
            ColumnDef("CUSTOMER_ID", "INTEGER", "INTEGER", False),
            ColumnDef("CURRENCY", "VARCHAR(8)", "VARCHAR", False),
            ColumnDef("ISSUE_DATE", "DATE", "DATE", False),
            ColumnDef("DUE_DATE", "DATE", "DATE", True),
            ColumnDef("TOTAL_AMOUNT", "NUMERIC(18,2)", "DOUBLE", False),
        )
        + METADATA_COLUMNS,
        "INVOICE_ID",
    ),
    "billing.invoice_lines": TableDef(
        "BILLING",
        "INVOICE_LINES",
        (
            ColumnDef("INVOICE_LINE_ID", "BIGINT", "BIGINT", False),
            ColumnDef("INVOICE_ID", "INTEGER", "INTEGER", False),
            ColumnDef("PLAN_CODE", "VARCHAR(64)", "VARCHAR", False),
            ColumnDef("QUANTITY", "INTEGER", "INTEGER", False),
            ColumnDef("UNIT_PRICE", "NUMERIC(18,2)", "DOUBLE", False),
            ColumnDef("AMOUNT", "NUMERIC(18,2)", "DOUBLE", False),
            ColumnDef("SERVICE_PERIOD_START", "DATE", "DATE", True),
            ColumnDef("SERVICE_PERIOD_END", "DATE", "DATE", True),
        )
        + METADATA_COLUMNS,
        "INVOICE_LINE_ID",
    ),
    "payments.payments": TableDef(
        "PAYMENTS",
        "PAYMENTS",
        (
            ColumnDef("PAYMENT_ID", "BIGINT", "BIGINT", False),
            ColumnDef("INVOICE_ID", "INTEGER", "INTEGER", False),
            ColumnDef("PAYMENT_REF", "VARCHAR(64)", "VARCHAR", False),
            ColumnDef("AMOUNT", "NUMERIC(18,2)", "DOUBLE", False),
            ColumnDef("PAID_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "PAYMENT_ID",
    ),
    "payments.refunds": TableDef(
        "PAYMENTS",
        "REFUNDS",
        (
            ColumnDef("REFUND_ID", "INTEGER", "INTEGER", False),
            ColumnDef("PAYMENT_ID", "BIGINT", "BIGINT", False),
            ColumnDef("AMOUNT", "NUMERIC(18,2)", "DOUBLE", False),
            ColumnDef("REFUNDED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "REFUND_ID",
    ),
    "product.plans": TableDef(
        "PRODUCT",
        "PLANS",
        (
            ColumnDef("PLAN_CODE", "VARCHAR(64)", "VARCHAR", False),
            ColumnDef("PLAN_NAME", "VARCHAR(128)", "VARCHAR", False),
            ColumnDef("VALID_FROM", "DATE", "DATE", False),
            ColumnDef("VALID_TO", "DATE", "DATE", True),
            ColumnDef("MONTHLY_PRICE", "NUMERIC(18,2)", "DOUBLE", False),
        )
        + METADATA_COLUMNS,
        "PLAN_CODE,VALID_FROM",
    ),
    "support.tickets": TableDef(
        "SUPPORT",
        "TICKETS",
        (
            ColumnDef("TICKET_ID", "BIGINT", "BIGINT", False),
            ColumnDef("CUSTOMER_ID", "INTEGER", "INTEGER", True),
            ColumnDef("SUBJECT", "VARCHAR(256)", "VARCHAR", False),
            ColumnDef("STATUS", "VARCHAR(32)", "VARCHAR", False),
            ColumnDef("CREATED_AT", "TIMESTAMP", "TIMESTAMP", False),
        )
        + METADATA_COLUMNS,
        "TICKET_ID",
    ),
}


def invoice_columns_for_version(version: str) -> tuple[ColumnDef, ...]:
    base = TABLES["billing.invoices"].columns[:5]
    status_col = (
        ColumnDef("INVOICE_STATUS", "VARCHAR(32)", "VARCHAR", False)
        if version == "v1"
        else ColumnDef("STATUS", "VARCHAR(32)", "VARCHAR", False)
    )
    tail = TABLES["billing.invoices"].columns[5:]
    return base + (status_col,) + tail


def invoice_line_amount_type(version: str, extract_date: str, bad_extract_date: str) -> str:
    if version == "v1" and extract_date == bad_extract_date:
        return "VARCHAR"
    return "DOUBLE"
