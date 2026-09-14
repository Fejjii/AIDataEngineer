"""Bounded deterministic dbt generation for the Vantara customer-revenue scenario."""

from __future__ import annotations

import hashlib
from uuid import UUID

from aide.capabilities.io import (
    GenerateTransformationInput,
    GenerateTransformationOutput,
    ModelDesign,
    TransformationFile,
)
from aide.connectors.snowflake.namespace import workflow_short_id
from aide.domain.identity import canonical_json_bytes
from aide.generation.validate import validate_generated_files

# Sibling of modelling.constants.REQUIRED_DEMO_MODELS; kept here to avoid a
# same-layer import. Unit tests assert the two tuples stay identical.
INTERVIEW_REQUIRED_MODELS = (
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

CURRENCY = (
    "case upper(CURRENCY) when '€' then 'EUR' when 'EUR' then 'EUR' "
    "when 'USD' then 'USD' when 'GBP' then 'GBP' else upper(CURRENCY) end"
)
WEBSITE = "regexp_replace(lower(trim(WEBSITE_DOMAIN)), '^www\\.', '')"


def generate_vantara_transformation(
    payload: GenerateTransformationInput,
) -> GenerateTransformationOutput:
    short = workflow_short_id(payload.workflow_id)
    files = (
        _sources_yml(short),
        _schema_yml(),
        *_model_files(),
    )
    validate_generated_files(files)
    names = tuple(
        item.path.split("/")[-1].removesuffix(".sql")
        for item in files
        if item.path.endswith(".sql")
    )
    required = set(INTERVIEW_REQUIRED_MODELS)
    missing = required.difference(names)
    if missing:
        raise ValueError(f"generation omitted required models: {sorted(missing)}")
    digest = hashlib.sha256(
        canonical_json_bytes(
            {"files": [{"path": item.path, "content": item.content} for item in files]}
        )
    ).hexdigest()
    designed = {unit.name for unit in payload.model_design.models}
    if not required.issubset(designed):
        raise ValueError(
            "accepted model design is missing required Interview MVP models: "
            f"{sorted(required.difference(designed))}"
        )
    return GenerateTransformationOutput(
        files=files,
        model_names=tuple(sorted(required)),
        content_sha256=digest,
    )


def _file(path: str, content: str, kind: str = "MODEL_SQL") -> TransformationFile:
    return TransformationFile(path=path, content=content.strip() + "\n", kind=kind)  # type: ignore[arg-type]


def _sources_yml(short: str) -> TransformationFile:
    blocks = []
    for name, schema, tables in (
        (
            "crm",
            f"{short}_CRM",
            (
                ("accounts", "ACCOUNTS"),
                ("contacts", "CONTACTS"),
                ("account_crosswalk", "ACCOUNT_CROSSWALK"),
            ),
        ),
        (
            "billing",
            f"{short}_BILLING",
            (
                ("customers", "CUSTOMERS"),
                ("subscriptions", "SUBSCRIPTIONS"),
                ("invoices", "INVOICES"),
                ("invoice_lines", "INVOICE_LINES"),
            ),
        ),
        ("payments", f"{short}_PAYMENTS", (("payments", "PAYMENTS"), ("refunds", "REFUNDS"))),
        ("product", f"{short}_PRODUCT", (("plans", "PLANS"),)),
        ("vantara_raw", f"{short}_BILLING", (("customers", "CUSTOMERS"), ("invoices", "INVOICES"))),
    ):
        table_yaml = "\n".join(
            f"      - name: {tname}\n        identifier: {ident}" for tname, ident in tables
        )
        blocks.append(
            f"""  - name: {name}
    database: "{{% if target.type == 'snowflake' %}}AIDE_DEV{{% endif %}}"
    schema: {schema}
    tables:
{table_yaml}"""
        )
    body = "version: 2\n\nsources:\n" + "\n".join(blocks) + "\n"
    return _file("models/sources.yml", body, "SOURCE_YML")


def _schema_yml() -> TransformationFile:
    models = []
    for name, column, extra in (
        ("stg_crm__accounts", "account_id", ""),
        ("stg_crm__contacts", "contact_id", ""),
        ("stg_crm__account_crosswalk", "account_id", ""),
        ("stg_billing__customers", "customer_id", ""),
        ("stg_billing__subscriptions", "subscription_id", ""),
        (
            "stg_billing__invoices",
            "invoice_id",
            "      - name: invoice_status\n        tests:\n          - not_null\n",
        ),
        ("stg_billing__invoice_lines", "invoice_line_id", ""),
        ("stg_payments__payments", "payment_id", ""),
        ("stg_payments__refunds", "refund_id", ""),
        ("stg_product__plans", "plan_code", ""),
        ("int_customer_deduplicated", "account_id", ""),
        ("int_customer_conformed", "billing_customer_id", ""),
        ("int_payments_deduplicated", "payment_id", ""),
        ("int_subscription_plan_history", "subscription_id", ""),
        ("snap_customer_conformed", "billing_customer_id", ""),
        ("dim_customer", "customer_sk", ""),
        ("dim_plan", "plan_sk", ""),
        ("dim_date", "date_day", ""),
        ("fct_invoice_line", "invoice_line_id", ""),
        ("fct_payment", "payment_id", ""),
        ("mart_customer_revenue_daily", "customer_sk", ""),
        ("fct_invoices", "invoice_id", ""),
    ):
        models.append(
            f"""  - name: {name}
    columns:
      - name: {column}
        tests:
          - not_null
{extra}"""
        )
    return _file("models/schema.yml", "version: 2\n\nmodels:\n" + "\n".join(models), "SCHEMA_YML")


def _model_files() -> tuple[TransformationFile, ...]:
    return (
        _file(
            "models/staging/stg_crm__accounts.sql",
            f"""
{{{{ config(materialized='view') }}}}
select
  ACCOUNT_ID as account_id,
  trim(ACCOUNT_NAME) as account_name,
  {WEBSITE} as website_domain,
  INDUSTRY as industry,
  COUNTRY as country,
  IS_DELETED as is_deleted,
  CREATED_AT as created_at,
  UPDATED_AT as updated_at,
  _LOADED_AT as _loaded_at
from {{{{ source('crm', 'accounts') }}}}
""",
        ),
        _file(
            "models/staging/stg_crm__contacts.sql",
            """
{{ config(materialized='view') }}
select
  CONTACT_ID as contact_id,
  ACCOUNT_ID as account_id,
  FIRST_NAME as first_name,
  LAST_NAME as last_name,
  '***' as email,
  '***' as phone,
  CREATED_AT as created_at,
  UPDATED_AT as updated_at,
  _LOADED_AT as _loaded_at
from {{ source('crm', 'contacts') }}
""",
        ),
        _file(
            "models/staging/stg_crm__account_crosswalk.sql",
            """
{{ config(materialized='view') }}
select
  ACCOUNT_ID as account_id,
  BILLING_CUSTOMER_ID as billing_customer_id,
  CREATED_AT as created_at,
  _LOADED_AT as _loaded_at
from {{ source('crm', 'account_crosswalk') }}
""",
        ),
        _file(
            "models/staging/stg_billing__customers.sql",
            """
{{ config(materialized='view') }}
select
  CUSTOMER_ID as customer_id,
  CUSTOMER_NAME as customer_name,
  CRM_ACCOUNT_ID as crm_account_id,
  BILLING_COUNTRY as billing_country,
  CREATED_AT as created_at,
  UPDATED_AT as updated_at,
  _LOADED_AT as _loaded_at
from {{ source('billing', 'customers') }}
""",
        ),
        _file(
            "models/staging/stg_billing__subscriptions.sql",
            """
{{ config(materialized='view') }}
select
  SUBSCRIPTION_ID as subscription_id,
  CUSTOMER_ID as customer_id,
  PLAN_CODE as plan_code,
  STATUS as status,
  START_DATE as start_date,
  END_DATE as end_date,
  UPDATED_AT as updated_at,
  _LOADED_AT as _loaded_at
from {{ source('billing', 'subscriptions') }}
""",
        ),
        _file(
            "models/staging/stg_billing__invoices.sql",
            f"""
{{{{ config(materialized='view') }}}}
select
  INVOICE_ID as invoice_id,
  CUSTOMER_ID as customer_id,
  {CURRENCY} as currency,
  ISSUE_DATE as issue_date,
  DUE_DATE as due_date,
  INVOICE_STATUS as invoice_status,
  TOTAL_AMOUNT as total_amount,
  _LOADED_AT as _loaded_at
from {{{{ source('billing', 'invoices') }}}}
""",
        ),
        _file(
            "models/staging/stg_billing__invoice_lines.sql",
            """
{{ config(materialized='view') }}
select
  INVOICE_LINE_ID as invoice_line_id,
  INVOICE_ID as invoice_id,
  PLAN_CODE as plan_code,
  QUANTITY as quantity,
  UNIT_PRICE as unit_price,
  AMOUNT as amount,
  SERVICE_PERIOD_START as service_period_start,
  SERVICE_PERIOD_END as service_period_end,
  _LOADED_AT as _loaded_at
from {{ source('billing', 'invoice_lines') }}
""",
        ),
        _file(
            "models/staging/stg_payments__payments.sql",
            """
{{ config(materialized='view') }}
select
  PAYMENT_ID as payment_id,
  INVOICE_ID as invoice_id,
  PAYMENT_REF as payment_ref,
  AMOUNT as amount,
  PAID_AT as paid_at,
  _LOADED_AT as _loaded_at
from {{ source('payments', 'payments') }}
""",
        ),
        _file(
            "models/staging/stg_payments__refunds.sql",
            """
{{ config(materialized='view') }}
select
  REFUND_ID as refund_id,
  PAYMENT_ID as payment_id,
  AMOUNT as amount,
  REFUNDED_AT as refunded_at,
  _LOADED_AT as _loaded_at
from {{ source('payments', 'refunds') }}
""",
        ),
        _file(
            "models/staging/stg_product__plans.sql",
            """
{{ config(materialized='view') }}
select
  PLAN_CODE as plan_code,
  PLAN_NAME as plan_name,
  VALID_FROM as valid_from,
  VALID_TO as valid_to,
  MONTHLY_PRICE as monthly_price,
  _LOADED_AT as _loaded_at
from {{ source('product', 'plans') }}
""",
        ),
        _file(
            "models/intermediate/int_customer_deduplicated.sql",
            """
{{ config(materialized='table') }}
select
  account_id,
  account_name,
  website_domain,
  industry,
  country,
  created_at,
  updated_at,
  _loaded_at
from (
  select
    *,
    row_number() over (
      partition by website_domain
      order by updated_at desc, account_id
    ) as rn
  from {{ ref('stg_crm__accounts') }}
) ranked
where rn = 1
""",
        ),
        _file(
            "models/intermediate/int_customer_conformed.sql",
            """
{{ config(materialized='table') }}
select
  billing.customer_id as billing_customer_id,
  coalesce(crm.account_id, billing.crm_account_id) as crm_account_id,
  coalesce(crm.account_name, billing.customer_name) as customer_name,
  billing.billing_country as billing_country,
  crm.website_domain as website_domain,
  billing.updated_at as updated_at,
  billing._loaded_at as _loaded_at
from {{ ref('stg_billing__customers') }} billing
left join {{ ref('stg_crm__account_crosswalk') }} xw
  on cast(xw.billing_customer_id as varchar) = cast(billing.customer_id as varchar)
left join {{ ref('int_customer_deduplicated') }} crm
  on crm.account_id = coalesce(xw.account_id, billing.crm_account_id)
""",
        ),
        _file(
            "models/intermediate/int_payments_deduplicated.sql",
            """
{{ config(materialized='table') }}
select
  payment_id,
  invoice_id,
  payment_ref,
  amount,
  paid_at,
  _loaded_at
from (
  select
    *,
    row_number() over (
      partition by invoice_id, payment_ref
      order by _loaded_at desc, payment_id
    ) as rn
  from {{ ref('stg_payments__payments') }}
) ranked
where rn = 1
""",
        ),
        _file(
            "models/intermediate/int_subscription_plan_history.sql",
            """
{{ config(materialized='table') }}
select
  subscription_id,
  customer_id,
  plan_code,
  status,
  start_date,
  end_date,
  updated_at,
  _loaded_at
from {{ ref('stg_billing__subscriptions') }}
""",
        ),
        _file(
            "models/intermediate/snap_customer_conformed.sql",
            """
{{ config(materialized='table') }}
select
  billing_customer_id,
  crm_account_id,
  customer_name,
  billing_country,
  website_domain,
  updated_at as valid_from,
  cast(null as timestamp) as valid_to,
  true as is_current,
  _loaded_at
from {{ ref('int_customer_conformed') }}
""",
        ),
        _file(
            "models/marts/dim_customer.sql",
            """
{{ config(materialized='table') }}
select
  md5(cast(billing_customer_id as varchar)) as customer_sk,
  billing_customer_id,
  crm_account_id,
  customer_name,
  billing_country,
  website_domain,
  valid_from,
  valid_to,
  is_current
from {{ ref('snap_customer_conformed') }}
where is_current
union all
select
  md5('-1') as customer_sk,
  -1 as billing_customer_id,
  cast(null as varchar) as crm_account_id,
  'Unknown customer' as customer_name,
  cast(null as varchar) as billing_country,
  cast(null as varchar) as website_domain,
  cast(null as timestamp) as valid_from,
  cast(null as timestamp) as valid_to,
  true as is_current
""",
        ),
        _file(
            "models/marts/dim_plan.sql",
            """
{{ config(materialized='table') }}
select
  md5(plan_code) as plan_sk,
  plan_code,
  plan_name,
  monthly_price,
  valid_from,
  valid_to
from {{ ref('stg_product__plans') }}
""",
        ),
        _file(
            "models/marts/dim_date.sql",
            """
{{ config(materialized='table') }}
select distinct
  cast(issue_date as date) as date_day,
  date_part('year', cast(issue_date as date)) as year,
  date_part('month', cast(issue_date as date)) as month
from {{ ref('stg_billing__invoices') }}
""",
        ),
        _file(
            "models/marts/fct_invoice_line.sql",
            """
{{ config(materialized='table') }}
select
  lines.invoice_line_id,
  lines.invoice_id,
  customers.customer_sk,
  plans.plan_sk,
  cast(invoices.issue_date as date) as date_day,
  lines.amount,
  invoices.currency,
  lines._loaded_at
from {{ ref('stg_billing__invoice_lines') }} lines
inner join {{ ref('stg_billing__invoices') }} invoices
  on lines.invoice_id = invoices.invoice_id
left join {{ ref('dim_customer') }} customers
  on cast(customers.billing_customer_id as varchar) = cast(invoices.customer_id as varchar)
left join {{ ref('dim_plan') }} plans
  on cast(plans.plan_code as varchar) = cast(lines.plan_code as varchar)
""",
        ),
        _file(
            "models/marts/fct_payment.sql",
            """
{{ config(materialized='table') }}
select
  payments.payment_id,
  payments.invoice_id,
  customers.customer_sk,
  payments.amount,
  payments.paid_at,
  cast(payments.paid_at as date) as date_day,
  payments._loaded_at
from {{ ref('int_payments_deduplicated') }} payments
inner join {{ ref('stg_billing__invoices') }} invoices
  on payments.invoice_id = invoices.invoice_id
left join {{ ref('dim_customer') }} customers
  on cast(customers.billing_customer_id as varchar) = cast(invoices.customer_id as varchar)
""",
        ),
        _file(
            "models/marts/mart_customer_revenue_daily.sql",
            """
{{ config(materialized='table') }}
select
  coalesce(invoiced.customer_sk, paid.customer_sk) as customer_sk,
  coalesce(invoiced.date_day, paid.date_day) as date_day,
  coalesce(invoiced.invoiced_amount, 0) as invoiced_amount,
  coalesce(paid.paid_amount, 0) as paid_amount
from (
  select customer_sk, date_day, sum(amount) as invoiced_amount
  from {{ ref('fct_invoice_line') }}
  group by 1, 2
) invoiced
full outer join (
  select customer_sk, date_day, sum(amount) as paid_amount
  from {{ ref('fct_payment') }}
  group by 1, 2
) paid
  on invoiced.customer_sk = paid.customer_sk
 and invoiced.date_day = paid.date_day
""",
        ),
        _file(
            "models/marts/fct_invoices.sql",
            """
{{ config(materialized='table') }}
select
  invoices.invoice_id,
  invoices.customer_id,
  customers.customer_name,
  invoices.currency,
  invoices.issue_date,
  invoices.invoice_status,
  invoices.total_amount
from {{ ref('stg_billing__invoices') }} as invoices
left join {{ ref('stg_billing__customers') }} as customers
  on invoices.customer_id = customers.customer_id
""",
        ),
    )


def generate_from_design(
    workflow_id: UUID, model_design: ModelDesign, fixture_version: str = "v1"
) -> GenerateTransformationOutput:
    return generate_vantara_transformation(
        GenerateTransformationInput(
            workflow_id=workflow_id,
            model_design=model_design,
            fixture_version=fixture_version,  # type: ignore[arg-type]
        )
    )
