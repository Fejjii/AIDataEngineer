"""Accepted modelling thresholds from docs/DATA_MODELLING_STRATEGY.md."""

from __future__ import annotations

VOLUME_M_MIN = 1_000_000
VOLUME_L_MIN = 50_000_000
VOLUME_XL_MIN = 1_000_000_001
IDENTIFIER_ALIGNED = 0.99
IDENTIFIER_PARTIAL = 0.9
GRAIN_UNIQUENESS = 0.999
WATERMARK_NULL_MAX = 0.01
APPROVAL_MODEL_COUNT = 40
WATERMARK_LOOKBACK_DAYS = 3

CHANGE_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
VOLUME_RANK = {"S": 1, "M": 2, "L": 3, "XL": 4}
LATENCY_RANK = {"MINUTES": 1, "HOURLY": 2, "DAILY": 3}

IDENTITY_COLUMN_HINTS = (
    "ACCOUNT_ID",
    "CUSTOMER_ID",
    "CRM_ACCOUNT_ID",
    "BILLING_CUSTOMER_ID",
)
MEASURE_COLUMN_HINTS = {
    "AMOUNT",
    "TOTAL_AMOUNT",
    "UNIT_PRICE",
    "QUANTITY",
    "MONTHLY_PRICE",
}
FACT_TABLE_HINTS = ("INVOICE_LINE", "PAYMENT", "REFUND", "ORDER")
VALID_FROM_NAMES = frozenset({"VALID_FROM", "EFFECTIVE_FROM", "BUS_FROM"})
VALID_TO_NAMES = frozenset({"VALID_TO", "EFFECTIVE_TO", "BUS_TO"})
UPDATED_AT_NAMES = frozenset({"UPDATED_AT", "UPDATE_TS", "MODIFIED_AT"})
CREATED_AT_NAMES = frozenset({"CREATED_AT", "CREATE_TS"})
LOADED_AT_NAMES = frozenset({"_LOADED_AT", "LOADED_AT"})
AUDIT_HIGH_HINTS = (
    "audit",
    "regulatory",
    "regulated",
    "sox",
    "gdpr",
    "hipaa",
    "pci",
    "compliance",
)
AUDIT_LOW_HINTS = ("no audit", "non-regulated", "unregulated", "internal only")
COST_HIGH_HINTS = ("cost sensitive", "minimize cost", "budget cap", "warehouse cost")
COST_LOW_HINTS = ("cost insensitive", "cost is not a concern")
STAGING_NAME = r"^stg_[a-z][a-z0-9]*__[a-z][a-z0-9_]*$"
INTERMEDIATE_NAME = r"^int_[a-z][a-z0-9_]*$"
DIMENSION_NAME = r"^dim_[a-z][a-z0-9_]*$"
FACT_NAME = r"^fct_[a-z][a-z0-9_]*$"
MART_NAME = r"^mart_[a-z][a-z0-9_]*$"
SNAPSHOT_NAME = r"^snap_[a-z][a-z0-9_]*$"
VAULT_KINDS = frozenset({"HUB", "LINK", "SATELLITE", "RAW_VAULT", "BUSINESS_VAULT"})
REQUIRED_DEMO_MODELS = (
    "stg_crm__accounts",
    "stg_crm__contacts",
    "stg_crm__account_crosswalk",
    "stg_billing__customers",
    "stg_billing__subscriptions",
    "stg_billing__invoices",
    "stg_billing__invoice_lines",
    "stg_payments__payments",
    "stg_payments__refunds",
    "stg_product__plans",
    "int_customer_deduplicated",
    "int_customer_conformed",
    "int_payments_deduplicated",
    "int_subscription_plan_history",
    "snap_customer_conformed",
    "dim_customer",
    "dim_plan",
    "dim_date",
    "fct_invoice_line",
    "fct_payment",
    "mart_customer_revenue_daily",
)
