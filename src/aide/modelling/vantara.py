"""Accepted Vantara demo requirement, catalog volumes, and org policy."""

from __future__ import annotations

from aide.capabilities.io import BusinessEntity, MetricSpec, RequirementSpec
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.modelling.context import ModellingContext, OrgModellingConfig
from aide.profiling.fixtures import CONNECTOR_ID, DEMO_SELECTED_ADDRESSES

VANTARA_FULL_ROW_COUNTS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("VANTARA_RAW", "CRM", "ACCOUNTS"), 27_500),
    (("VANTARA_RAW", "CRM", "CONTACTS"), 82_000),
    (("VANTARA_RAW", "CRM", "ACCOUNT_CROSSWALK"), 24_900),
    (("VANTARA_RAW", "BILLING", "CUSTOMERS"), 25_600),
    (("VANTARA_RAW", "BILLING", "SUBSCRIPTIONS"), 61_000),
    (("VANTARA_RAW", "BILLING", "INVOICES"), 1_240_000),
    (("VANTARA_RAW", "BILLING", "INVOICE_LINES"), 4_100_000),
    (("VANTARA_RAW", "PAYMENTS", "PAYMENTS"), 1_130_000),
    (("VANTARA_RAW", "PAYMENTS", "REFUNDS"), 38_000),
    (("VANTARA_RAW", "PRODUCT", "PLANS"), 96),
)

VANTARA_ORG_CONFIG = OrgModellingConfig(
    auditability="LOW",
    cost_sensitivity="UNKNOWN",
    naming_convention="DBT_DEFAULT",
)


def vantara_demo_requirement() -> RequirementSpec:
    return RequirementSpec(
        goal=(
            "Build a customer revenue analytical data product from our CRM and billing data. "
            "Customers are duplicated in the CRM, so deduplicate them. Reconcile invoices "
            "against payments. Keep history of plan changes."
        ),
        deliverable_type="ANALYTICAL_DATA_PRODUCT",
        business_entities=(
            BusinessEntity(name="customer", description="conformed customer"),
            BusinessEntity(name="plan", description="product plan"),
            BusinessEntity(name="invoice_line", description="invoice line"),
            BusinessEntity(name="payment", description="payment"),
            BusinessEntity(name="revenue", description="daily customer revenue"),
        ),
        metrics=(
            MetricSpec(
                name="invoiced_amount",
                definition="SUM(invoice_line.amount)",
                ambiguous=False,
            ),
            MetricSpec(
                name="paid_amount",
                definition="SUM(payment.amount)",
                ambiguous=False,
            ),
            MetricSpec(
                name="mrr_estimate",
                definition="monthly recurring revenue",
                ambiguous=False,
            ),
        ),
        grain_hints=("customer", "date_day"),
        history_requirements="FULL_HISTORY",
        freshness_requirement="daily",
        consumers=("BI",),
        constraints=("deduplicate CRM accounts", "reconcile invoices against payments"),
        ambiguities=(),
        out_of_scope=("support tickets", "usage telemetry"),
    )


def vantara_modelling_context() -> ModellingContext:
    return ModellingContext(
        org=VANTARA_ORG_CONFIG,
        vendor="snowflake",
        dialect="snowflake",
        catalog_row_counts=VANTARA_FULL_ROW_COUNTS,
        require_demo_models=True,
    )


def vantara_required_models() -> tuple[str, ...]:
    return REQUIRED_DEMO_MODELS


def vantara_selected_addresses() -> tuple[tuple[str, str, str], ...]:
    return DEMO_SELECTED_ADDRESSES


def vantara_connector_id() -> str:
    return CONNECTOR_ID
