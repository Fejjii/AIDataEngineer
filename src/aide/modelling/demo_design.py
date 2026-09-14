"""Recorded Vantara ModelDesign used by DESIGN tests and replay fixtures."""

from __future__ import annotations

from typing import Literal

from aide.capabilities.io import (
    DedupRule,
    IncrementalConfig,
    ModelColumn,
    ModelDesign,
    ModelDesignUnit,
    NamingConvention,
    physical_layer_names,
)
from aide.domain.sql import AssetKind, AssetRef

PLACEHOLDER_DIGEST = "0" * 64
PiiHandling = Literal["masked", "excluded", "hashed"]


def _asset(schema: str, table: str) -> AssetRef:
    return AssetRef(
        connector_id="snowflake_ro",
        address=("VANTARA_RAW", schema, table),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )


def _c(
    asset: AssetRef,
    raw: str,
    data_type: str,
    *,
    name: str | None = None,
    expr: str | None = None,
    tests: tuple[str, ...] = (),
    is_pii: bool = False,
    pii_handling: PiiHandling | None = None,
) -> ModelColumn:
    return ModelColumn(
        name=name or raw.lower(),
        expression=expr or raw,
        data_type=data_type,
        tests=tests,
        source_asset=asset,
        source_column=raw,
        is_pii=is_pii,
        pii_handling=pii_handling,
    )


def _d(
    name: str,
    expression: str,
    data_type: str,
    *,
    tests: tuple[str, ...] = (),
) -> ModelColumn:
    return ModelColumn(
        name=name,
        expression=expression,
        data_type=data_type,
        tests=tests,
    )


def vantara_model_design(
    *,
    architecture_decision_digest: str = PLACEHOLDER_DIGEST,
    naming: NamingConvention = "DBT_DEFAULT",
) -> ModelDesign:
    crm_accounts = _asset("CRM", "ACCOUNTS")
    crm_contacts = _asset("CRM", "CONTACTS")
    crm_crosswalk = _asset("CRM", "ACCOUNT_CROSSWALK")
    billing_customers = _asset("BILLING", "CUSTOMERS")
    billing_subs = _asset("BILLING", "SUBSCRIPTIONS")
    billing_invoices = _asset("BILLING", "INVOICES")
    billing_lines = _asset("BILLING", "INVOICE_LINES")
    payments = _asset("PAYMENTS", "PAYMENTS")
    refunds = _asset("PAYMENTS", "REFUNDS")
    plans = _asset("PRODUCT", "PLANS")
    website_expr = "regexp_replace(lower(trim(WEBSITE_DOMAIN)), '^www.', '')"
    currency_expr = (
        "case upper(CURRENCY) when '€' then 'EUR' when 'EUR' then 'EUR' "
        "when 'USD' then 'USD' when 'GBP' then 'GBP' else upper(CURRENCY) end"
    )
    models = (
        _staging(
            "stg_crm__accounts",
            crm_accounts,
            (
                _c(crm_accounts, "ACCOUNT_ID", "VARCHAR", tests=("unique", "not_null")),
                _c(crm_accounts, "ACCOUNT_NAME", "VARCHAR", expr="trim(ACCOUNT_NAME)"),
                _c(crm_accounts, "WEBSITE_DOMAIN", "VARCHAR", expr=website_expr),
                _c(crm_accounts, "INDUSTRY", "VARCHAR"),
                _c(crm_accounts, "COUNTRY", "VARCHAR"),
                _c(crm_accounts, "IS_DELETED", "BOOLEAN"),
                _c(crm_accounts, "CREATED_AT", "TIMESTAMP"),
                _c(crm_accounts, "UPDATED_AT", "TIMESTAMP"),
                _c(crm_accounts, "_LOADED_AT", "TIMESTAMP"),
            ),
        ),
        _staging(
            "stg_crm__contacts",
            crm_contacts,
            (
                _c(crm_contacts, "CONTACT_ID", "VARCHAR", tests=("unique", "not_null")),
                _c(crm_contacts, "ACCOUNT_ID", "VARCHAR"),
                _c(
                    crm_contacts,
                    "EMAIL",
                    "VARCHAR",
                    is_pii=True,
                    pii_handling="masked",
                ),
                _c(
                    crm_contacts,
                    "PHONE",
                    "VARCHAR",
                    is_pii=True,
                    pii_handling="masked",
                ),
            ),
        ),
        _staging(
            "stg_crm__account_crosswalk",
            crm_crosswalk,
            (
                _c(crm_crosswalk, "ACCOUNT_ID", "VARCHAR"),
                _c(crm_crosswalk, "BILLING_CUSTOMER_ID", "NUMBER"),
            ),
        ),
        _staging(
            "stg_billing__customers",
            billing_customers,
            (
                _c(billing_customers, "CUSTOMER_ID", "NUMBER", tests=("unique", "not_null")),
                _c(billing_customers, "CUSTOMER_NAME", "VARCHAR"),
                _c(billing_customers, "CRM_ACCOUNT_ID", "VARCHAR"),
                _c(billing_customers, "BILLING_COUNTRY", "VARCHAR"),
                _c(billing_customers, "UPDATED_AT", "TIMESTAMP"),
            ),
        ),
        _staging(
            "stg_billing__subscriptions",
            billing_subs,
            (
                _c(billing_subs, "SUBSCRIPTION_ID", "NUMBER"),
                _c(billing_subs, "CUSTOMER_ID", "NUMBER"),
                _c(billing_subs, "PLAN_CODE", "VARCHAR"),
                _c(
                    billing_subs,
                    "STATUS",
                    "VARCHAR",
                    expr="lower(STATUS)",
                    tests=("accepted_values",),
                ),
                _c(billing_subs, "START_DATE", "DATE"),
                _c(billing_subs, "END_DATE", "DATE"),
                _c(billing_subs, "UPDATED_AT", "TIMESTAMP"),
            ),
        ),
        _staging(
            "stg_billing__invoices",
            billing_invoices,
            (
                _c(billing_invoices, "INVOICE_ID", "NUMBER", tests=("unique", "not_null")),
                _c(billing_invoices, "CUSTOMER_ID", "NUMBER"),
                _c(
                    billing_invoices,
                    "CURRENCY",
                    "VARCHAR",
                    expr=currency_expr,
                    tests=("accepted_values",),
                ),
                _c(billing_invoices, "ISSUE_DATE", "DATE"),
                _c(billing_invoices, "DUE_DATE", "DATE"),
                _c(billing_invoices, "TOTAL_AMOUNT", "NUMBER"),
                _c(billing_invoices, "STATUS", "VARCHAR"),
                _c(
                    billing_invoices,
                    "_LOADED_AT",
                    "TIMESTAMP",
                    name="updated_at",
                ),
            ),
        ),
        _staging(
            "stg_billing__invoice_lines",
            billing_lines,
            (
                _c(billing_lines, "INVOICE_LINE_ID", "NUMBER", tests=("unique", "not_null")),
                _c(billing_lines, "INVOICE_ID", "NUMBER"),
                _c(billing_lines, "PLAN_CODE", "VARCHAR"),
                _c(billing_lines, "QUANTITY", "NUMBER"),
                _c(billing_lines, "UNIT_PRICE", "NUMBER"),
                _c(
                    billing_lines,
                    "AMOUNT",
                    "NUMBER",
                    expr="try_to_number(AMOUNT::varchar)",
                ),
                _c(billing_lines, "_LOADED_AT", "TIMESTAMP"),
            ),
        ),
        _staging(
            "stg_payments__payments",
            payments,
            (
                _c(payments, "PAYMENT_ID", "NUMBER"),
                _c(payments, "INVOICE_ID", "NUMBER"),
                _c(payments, "PAYMENT_REF", "VARCHAR"),
                _c(payments, "AMOUNT", "NUMBER"),
                _c(
                    payments,
                    "PAID_AT",
                    "TIMESTAMP",
                    expr="convert_timezone('UTC', PAID_AT)",
                ),
                _c(payments, "_LOADED_AT", "TIMESTAMP"),
            ),
        ),
        _staging(
            "stg_payments__refunds",
            refunds,
            (
                _c(refunds, "REFUND_ID", "NUMBER"),
                _c(refunds, "PAYMENT_ID", "NUMBER"),
                _c(refunds, "AMOUNT", "NUMBER"),
                _c(refunds, "REFUNDED_AT", "TIMESTAMP"),
            ),
        ),
        _staging(
            "stg_product__plans",
            plans,
            (
                _c(plans, "PLAN_CODE", "VARCHAR"),
                _c(plans, "PLAN_NAME", "VARCHAR"),
                _c(plans, "VALID_FROM", "DATE"),
                _c(plans, "VALID_TO", "DATE"),
                _c(plans, "MONTHLY_PRICE", "NUMBER"),
            ),
        ),
        ModelDesignUnit(
            name="int_customer_deduplicated",
            model_kind="INTERMEDIATE",
            layer="intermediate",
            source_assets=(crm_accounts,),
            grain=("account_id",),
            columns=(
                _d("account_id", "account_id", "VARCHAR"),
                _d("account_name", "account_name", "VARCHAR"),
                _d("website_domain", "website_domain", "VARCHAR"),
                _d("updated_at", "updated_at", "TIMESTAMP"),
            ),
            materialization="table",
            unique_key=("account_id",),
            dedup_rule=DedupRule(
                partition=("website_domain",),
                order_by=("updated_at desc", "is_deleted asc"),
                description="latest UPDATED_AT within normalized WEBSITE_DOMAIN, not deleted",
            ),
            dependencies=("stg_crm__accounts",),
            assumptions=("survivorship by latest UPDATED_AT is acceptable for CRM duplicates",),
            rule_refs=("F4",),
        ),
        ModelDesignUnit(
            name="int_customer_conformed",
            model_kind="INTERMEDIATE",
            layer="intermediate",
            source_assets=(crm_accounts, crm_crosswalk, billing_customers),
            grain=("customer_id",),
            columns=(
                _d("customer_id", "customer_id", "NUMBER"),
                _d("account_id", "account_id", "VARCHAR"),
                _d("customer_name", "coalesce(customer_name, account_name)", "VARCHAR"),
                _d("updated_at", "updated_at", "TIMESTAMP"),
            ),
            materialization="table",
            unique_key=("customer_id",),
            dependencies=(
                "int_customer_deduplicated",
                "stg_crm__account_crosswalk",
                "stg_billing__customers",
            ),
            assumptions=("unknown member used for billing customers without a crosswalk",),
            rule_refs=("F4",),
        ),
        ModelDesignUnit(
            name="int_payments_deduplicated",
            model_kind="INTERMEDIATE",
            layer="intermediate",
            source_assets=(payments,),
            grain=("payment_id",),
            columns=(
                _d("payment_id", "payment_id", "NUMBER"),
                _d("invoice_id", "invoice_id", "NUMBER"),
                _d("payment_ref", "payment_ref", "VARCHAR"),
                _d("amount", "amount", "NUMBER"),
                _d("paid_at", "paid_at", "TIMESTAMP"),
                _d("_loaded_at", "_loaded_at", "TIMESTAMP"),
            ),
            materialization="table",
            unique_key=("payment_id",),
            dedup_rule=DedupRule(
                partition=("invoice_id", "payment_ref"),
                order_by=("_loaded_at desc",),
                description="keep latest _LOADED_AT for (invoice_id, payment_ref)",
            ),
            dependencies=("stg_payments__payments",),
            rule_refs=("F4",),
        ),
        ModelDesignUnit(
            name="int_subscription_plan_history",
            model_kind="INTERMEDIATE",
            layer="intermediate",
            source_assets=(plans, billing_subs),
            grain=("plan_code", "valid_from"),
            columns=(
                _d("plan_code", "plan_code", "VARCHAR"),
                _d("plan_name", "plan_name", "VARCHAR"),
                _d("valid_from", "valid_from", "DATE"),
                _d("valid_to", "valid_to", "DATE"),
                _d("monthly_price", "monthly_price", "NUMBER"),
            ),
            materialization="table",
            unique_key=("plan_code", "valid_from"),
            history_strategy="source_validity_intervals",
            dependencies=("stg_product__plans", "stg_billing__subscriptions"),
            rule_refs=("D1", "D6"),
        ),
        ModelDesignUnit(
            name="snap_customer_conformed",
            model_kind="SNAPSHOT",
            layer="intermediate",
            grain=("customer_id",),
            columns=(
                _d("customer_id", "customer_id", "NUMBER"),
                _d("updated_at", "updated_at", "TIMESTAMP"),
            ),
            materialization="snapshot",
            unique_key=("customer_id",),
            watermark="updated_at",
            history_strategy="snapshot_timestamp",
            dependencies=("int_customer_conformed",),
            rule_refs=("D7",),
        ),
        ModelDesignUnit(
            name="dim_customer",
            model_kind="DIMENSION",
            layer="marts",
            grain=("customer_sk",),
            columns=(
                _d("customer_sk", "surrogate_key(customer_id, valid_from)", "VARCHAR"),
                _d("customer_id", "customer_id", "NUMBER", tests=("not_null",)),
                _d("customer_name", "customer_name", "VARCHAR"),
                _d("valid_from", "valid_from", "TIMESTAMP"),
                _d("valid_to", "valid_to", "TIMESTAMP"),
                _d("is_current", "is_current", "BOOLEAN"),
            ),
            materialization="table",
            unique_key=("customer_sk",),
            history_strategy="snapshot_timestamp",
            tracked_scd2_columns=("customer_name", "account_id"),
            tests=("unique", "one_current_per_customer"),
            dependencies=("snap_customer_conformed",),
            surrogate_key="customer_sk",
            natural_keys=("customer_id",),
            scd_type="SCD2",
            rule_refs=("D1", "D7"),
        ),
        ModelDesignUnit(
            name="dim_plan",
            model_kind="DIMENSION",
            layer="marts",
            grain=("plan_sk",),
            columns=(
                _d("plan_sk", "surrogate_key(plan_code, valid_from)", "VARCHAR"),
                _d("plan_code", "plan_code", "VARCHAR"),
                _d("plan_name", "plan_name", "VARCHAR"),
                _d("valid_from", "valid_from", "DATE"),
                _d("valid_to", "valid_to", "DATE"),
                _d("is_current", "valid_to is null", "BOOLEAN"),
            ),
            materialization="table",
            unique_key=("plan_sk",),
            history_strategy="source_validity_intervals",
            tracked_scd2_columns=("plan_name", "monthly_price"),
            dependencies=("int_subscription_plan_history",),
            surrogate_key="plan_sk",
            natural_keys=("plan_code", "valid_from"),
            scd_type="SCD2",
            rule_refs=("D1", "D6"),
        ),
        ModelDesignUnit(
            name="dim_date",
            model_kind="DIMENSION",
            layer="marts",
            grain=("date_day",),
            columns=(
                _d("date_day", "date_day", "DATE"),
                _d("year", "year(date_day)", "NUMBER"),
                _d("month", "month(date_day)", "NUMBER"),
            ),
            materialization="table",
            unique_key=("date_day",),
            history_strategy="static",
            scd_type="STATIC",
            rule_refs=("D8",),
        ),
        ModelDesignUnit(
            name="fct_invoice_line",
            model_kind="FACT",
            layer="marts",
            source_assets=(billing_lines, billing_invoices),
            grain=("invoice_line_id",),
            columns=(
                _d("invoice_line_id", "invoice_line_id", "NUMBER", tests=("unique", "not_null")),
                _d("invoice_id", "invoice_id", "NUMBER"),
                _d("customer_sk", "customer_sk", "VARCHAR"),
                _d("plan_sk", "plan_sk", "VARCHAR"),
                _d("date_day", "issue_date", "DATE"),
                _d("amount", "amount", "NUMBER"),
                _d("currency", "currency", "VARCHAR"),
            ),
            materialization="incremental",
            unique_key=("invoice_line_id",),
            watermark="_loaded_at",
            incremental=IncrementalConfig(
                strategy="merge",
                unique_key=("invoice_line_id",),
                watermark_column="_loaded_at",
                lookback_days=3,
            ),
            tests=("unique", "not_null", "reconciliation_sum"),
            dependencies=(
                "stg_billing__invoice_lines",
                "stg_billing__invoices",
                "dim_customer",
                "dim_plan",
                "dim_date",
            ),
            rule_refs=("F1", "M3"),
        ),
        ModelDesignUnit(
            name="fct_payment",
            model_kind="FACT",
            layer="marts",
            source_assets=(payments,),
            grain=("payment_id",),
            columns=(
                _d("payment_id", "payment_id", "NUMBER", tests=("unique", "not_null")),
                _d("invoice_id", "invoice_id", "NUMBER"),
                _d("amount", "amount", "NUMBER"),
                _d("paid_at", "paid_at", "TIMESTAMP"),
            ),
            materialization="incremental",
            unique_key=("payment_id",),
            watermark="_loaded_at",
            incremental=IncrementalConfig(
                strategy="merge",
                unique_key=("payment_id",),
                watermark_column="_loaded_at",
                lookback_days=3,
            ),
            dedup_rule=DedupRule(
                partition=("invoice_id", "payment_ref"),
                order_by=("_loaded_at desc",),
                description="implemented in int_payments_deduplicated",
            ),
            tests=("unique", "reconciliation_sum"),
            dependencies=("int_payments_deduplicated", "dim_customer", "dim_date"),
            rule_refs=("F1", "F4", "M3"),
        ),
        ModelDesignUnit(
            name="mart_customer_revenue_daily",
            model_kind="MART",
            layer="marts",
            grain=("customer_sk", "date_day"),
            columns=(
                _d("customer_sk", "customer_sk", "VARCHAR"),
                _d("date_day", "date_day", "DATE"),
                _d("invoiced_amount", "sum(invoiced_amount)", "NUMBER"),
                _d("paid_amount", "sum(paid_amount)", "NUMBER"),
                _d("mrr_estimate", "mrr_estimate", "NUMBER"),
            ),
            materialization="table",
            unique_key=("customer_sk", "date_day"),
            tests=("unique", "paid_lte_invoiced"),
            dependencies=("fct_invoice_line", "fct_payment", "dim_customer", "dim_date"),
            rule_refs=("F2", "M6"),
        ),
    )
    return ModelDesign(
        layers=("staging", "intermediate", "marts"),
        physical_layer_names=physical_layer_names(naming, "STAGING_INTERMEDIATE_MARTS"),
        models=models,
        relationships=(
            "fct_invoice_line.customer_sk -> dim_customer.customer_sk",
            "fct_invoice_line.plan_sk -> dim_plan.plan_sk",
            "fct_payment.invoice_id -> fct_invoice_line.invoice_id",
        ),
        tests=("grain_unique", "not_null_sk", "reconciliation_sum"),
        assumptions=(
            "CRM survivorship uses latest UPDATED_AT within normalized domain",
            "revenue is invoiced with paid alongside",
        ),
        architecture_decision_digest=architecture_decision_digest,
    )


def _staging(name: str, asset: AssetRef, columns: tuple[ModelColumn, ...]) -> ModelDesignUnit:
    return ModelDesignUnit(
        name=name,
        model_kind="STAGING",
        layer="staging",
        source_assets=(asset,),
        grain=(columns[0].name,),
        columns=columns,
        materialization="view",
        unique_key=(columns[0].name,),
        rule_refs=("L1", "M1"),
    )


def vantara_model_design_payload(digest: str = PLACEHOLDER_DIGEST) -> dict[str, object]:
    return vantara_model_design(architecture_decision_digest=digest).model_dump(mode="json")
