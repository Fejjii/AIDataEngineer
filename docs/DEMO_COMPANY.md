# Synthetic Enterprise — Vantara Systems

**Task:** DE 001 · **Status:** ACCEPTED

Vantara Systems is a fictional B2B SaaS company (workflow-automation software, ~25 000
customer accounts, EUR/USD/GBP billing) whose operational systems land daily extracts in a
Snowflake `RAW` database. All data is generated deterministically (seeded) by the
`synthetic/vantara` generator into PostgreSQL (source-system stand-in) and loaded into
Snowflake `VANTARA_RAW` by a loader script. The same fixtures feed the DuckDB-backed fakes.

---

## 1. Source systems and schemas

| Source system (fictional) | Snowflake schema | Domain | Extract style |
|---|---|---|---|
| **OrbitCRM** | `VANTARA_RAW.CRM` | Accounts, contacts, opportunities | Daily full extract; **v1 → v2 schema change mid-history** |
| **LedgerLine Billing** | `VANTARA_RAW.BILLING` | Customers, subscriptions, invoices, invoice lines | Daily incremental by `UPDATED_AT`; late-arriving corrections |
| **PayBridge** | `VANTARA_RAW.PAYMENTS` | Payments, refunds | Batch files; **duplicate re-deliveries** |
| **Product catalog service** | `VANTARA_RAW.PRODUCT` | Plans with validity intervals | Full extract; history in source |
| **HelpDesk** (optional) | `VANTARA_RAW.SUPPORT` | Tickets | Daily incremental; not needed for the requirement (tests relevance selection) |
| **Usage telemetry** (optional, future) | `VANTARA_RAW.USAGE` | Feature usage events | Large volume; excluded in V1 (tests budgets if enabled) |

Every RAW table has `_LOADED_AT TIMESTAMP_NTZ`, `_EXTRACT_DATE DATE`, `_SOURCE_FILE VARCHAR`.

## 2. Tables and approximate volumes

| Table | Grain | Rows (approx.) | Key columns | Notes |
|---|---|---|---|---|
| `CRM.ACCOUNTS` | account | 27 500 | `ACCOUNT_ID` (uuid) | ~7 % duplicate accounts (same company, different casing/suffix, different `ACCOUNT_ID`); `WEBSITE_DOMAIN`, `INDUSTRY`, `COUNTRY`, `OWNER_ID`, `CREATED_AT`, `UPDATED_AT`, `IS_DELETED` |
| `CRM.CONTACTS` | contact | 82 000 | `CONTACT_ID` | `ACCOUNT_ID` FK; email PII (masked in samples); 2 % orphan contacts |
| `CRM.OPPORTUNITIES` | opportunity | 41 000 | `OPPORTUNITY_ID` | stage history; not required |
| `CRM.ACCOUNT_CROSSWALK` | account ↔ billing customer | 24 900 | (`ACCOUNT_ID`, `BILLING_CUSTOMER_ID`) | 3.1 % billing customers missing a crosswalk row |
| `BILLING.CUSTOMERS` | billing customer | 25 600 | `CUSTOMER_ID` (int) | `CRM_ACCOUNT_ID` sometimes null; `BILLING_COUNTRY` uses ISO-2 while CRM uses names |
| `BILLING.SUBSCRIPTIONS` | subscription | 61 000 | `SUBSCRIPTION_ID` | `PLAN_CODE`, `STATUS` (`active/paused/cancelled/ACTIVE/Cancelled` inconsistencies), `START_DATE`, `END_DATE`, `UPDATED_AT` |
| `BILLING.INVOICES` | invoice | 1 240 000 | `INVOICE_ID` | `CURRENCY` (`EUR/eur/€/USD/GBP`), `ISSUE_DATE`, `DUE_DATE`, **`INVOICE_STATUS` (v1) → `STATUS` (v2 from 2026-07)**, `TOTAL_AMOUNT`, 0.4 % invoices referencing unknown customers |
| `BILLING.INVOICE_LINES` | invoice line | 4 100 000 | `INVOICE_LINE_ID` | `INVOICE_ID`, `PLAN_CODE`, `QUANTITY`, `UNIT_PRICE`, `AMOUNT`, `SERVICE_PERIOD_START/END`; amounts as `NUMBER(18,2)` in v1 and `VARCHAR` in one bad extract day |
| `PAYMENTS.PAYMENTS` | payment | 1 130 000 (+1.5 % dupes) | `PAYMENT_ID` | `INVOICE_ID`, `PAYMENT_REF`, `AMOUNT`, `PAID_AT` (UTC) vs `ISSUE_DATE` (local date) mixing; duplicate rows with different `_LOADED_AT` |
| `PAYMENTS.REFUNDS` | refund | 38 000 | `REFUND_ID` | `PAYMENT_ID` FK |
| `PRODUCT.PLANS` | plan version | 96 | (`PLAN_CODE`, `VALID_FROM`) | renames (`Pro` → `Professional`), price changes; `VALID_FROM/VALID_TO` |
| `SUPPORT.TICKETS` | ticket | 310 000 | `TICKET_ID` | irrelevant to requirement |
| `USAGE.EVENTS` (optional) | event | 20 000 000 | `EVENT_ID` | disabled by default |

Total ≈ 6.9 M rows without usage; fits an X-Small warehouse and a DuckDB fake.

## 3. Business requirement (demo request)

> "Build a customer revenue analytical data product from our CRM and billing data. Customers
> are duplicated in the CRM, so deduplicate them. Reconcile invoices against payments. Keep
> history of plan changes. Add quality tests, document lineage and prepare it for deployment."

Clarifications the system should ask: revenue recognition basis (invoiced vs paid) and the
definition of *active customer*. Answers used in the demo: invoiced, with paid alongside;
active = has an active subscription on the date.

## 4. Data problems planted (and how the platform must respond)

| # | Problem | Where | Expected detection | Expected handling |
|---|---|---|---|---|
| P1 | Duplicate accounts | `CRM.ACCOUNTS` (normalized domain groups) | `profile_dataset` candidate key on `lower(trim(WEBSITE_DOMAIN))` < 1.0; `duplicate_groups_estimate` | `int_customer_deduplicated` with survivorship rule (latest `UPDATED_AT`, not deleted); `dedup_effectiveness` check |
| P2 | Missing values | `BILLING.CUSTOMERS.CRM_ACCOUNT_ID` nulls; `INVOICES.DUE_DATE` nulls | null ratios | staging coalesce via crosswalk; `not_null` tests where required; unknown-member rows in dims |
| P3 | Different identifiers | uuid vs int; crosswalk incomplete | `infer_relationships` inclusion 0.962 | conformed `dim_customer` with crosswalk + unknown member; relationship test with documented orphan ratio |
| P4 | Naming inconsistencies | `STATUS` casing; `CURRENCY` variants; country names vs ISO | `accepted_values` profile | standardization in staging; `accepted_values` tests |
| P5 | Invalid relationships | invoices → unknown customers; orphan contacts | inclusion ratios < 1 | relationship tests at WARN with orphan handling; reconciliation excludes and reports |
| P6 | Late-arriving data | payments arriving days after invoices; corrections to invoices | watermark analysis | incremental merge with 3-day lookback; snapshot-based periodic mart |
| P7 | Incremental updates | `UPDATED_AT` on billing; re-extracts | | incremental strategy (M3) |
| P8 | Schema differences | `INVOICE_STATUS` → `STATUS` (v2); `INVOICE_LINES.AMOUNT` varchar day | `detect_schema_drift` | **Failure scenario F1**; type cast with `TRY_TO_NUMBER` + `type_conformance` test |
| P9 | Timezone mixing | `PAID_AT` UTC vs local dates | profile min/max hints | explicit `CONVERT_TIMEZONE` in staging; documented |
| P10 | Duplicate payments | `PAYMENTS.PAYMENTS` | uniqueness < 1 on (`INVOICE_ID`,`PAYMENT_REF`) | **Failure scenario F2**; dedup on latest `_LOADED_AT` |

## 5. Intentional pipeline failures

| Id | Trigger | Failure class | Repair expected |
|---|---|---|---|
| **F1** | Discovery snapshot taken on RAW fixture *v1* (column `INVOICE_STATUS`); before generation the fake/loader applies *v2* (column renamed to `STATUS`). Generated `stg_billing__invoices` references `INVOICE_STATUS`. | `SCHEMA_MISMATCH` (Snowflake 000904 invalid identifier) at `validate_query` (pre-execution) or `execute_transformation` | `inspect_failure` shows drift `renamed_candidates [INVOICE_STATUS→STATUS, 0.91]`; `diagnose_failure` patches the staging model; compile + EXPLAIN pass |
| **F2** | Duplicate payment rows | `DBT_TEST` (`unique` on `fct_payment.payment_id` / grain) and `DATA_QUALITY` (`reconciliation_sum` over-count) | patch `int_payments_deduplicated` with `qualify row_number() over (partition by invoice_id, payment_ref order by _loaded_at desc) = 1`; rebuild `int_payments_deduplicated+`; tests and reconciliation pass |

Both must be repaired within budget (≤ 2 per task, ≤ 4 per workflow), with distinct
hypothesis hashes.

## 6. Target modelling architecture

Chosen by the rule table (`docs/DATA_MODELLING_STRATEGY.md` §6): layered
staging → intermediate → marts; star schema; SCD2 dims; incremental facts.

| Layer | Models |
|---|---|
| Staging (views) | `stg_crm__accounts`, `stg_crm__contacts`, `stg_crm__account_crosswalk`, `stg_billing__customers`, `stg_billing__subscriptions`, `stg_billing__invoices`, `stg_billing__invoice_lines`, `stg_payments__payments`, `stg_payments__refunds`, `stg_product__plans` |
| Intermediate (tables) | `int_customer_deduplicated` (survivorship), `int_customer_conformed` (crosswalk + unknown member), `int_payments_deduplicated`, `int_subscription_plan_history` |
| Dimensions | `dim_customer` (SCD2 via dbt snapshot on conformed customer), `dim_plan` (SCD2 from source validity intervals), `dim_date` (static), `dim_subscription_status` (small) |
| Facts | `fct_invoice_line` (incremental merge, grain invoice_line_id), `fct_payment` (incremental merge, grain payment_id), `fct_refund` |
| Marts | `mart_customer_revenue_daily` (grain customer_sk × date_day: invoiced_amount, paid_amount, refunded_amount, open_amount, active_subscriptions, mrr_estimate) |
| Snapshots | `snap_customer_conformed` |

## 7. Target analytical data product

`mart_customer_revenue_daily` plus the star (`dim_customer`, `dim_plan`, `dim_date`,
`fct_invoice_line`, `fct_payment`) exposed in `AIDE_DEV.WF<ID>_MARTS` (DEV) and, after
approval, `AIDE_STAGING.MARTS`. BI-ready: conformed customer with current flag, plan
history, daily revenue and payment reconciliation.

## 8. Quality requirements (must all pass on final build)

- Uniqueness on all surrogate keys and declared grains.
- `dim_customer`: exactly one current row per conformed customer; no interval overlaps.
- `fct_invoice_line.amount` reconciles to `stg_billing__invoice_lines` (after documented type handling) within 0.0 %.
- `fct_payment.amount` reconciles to deduplicated payments within 0.0 %.
- Paid ≤ invoiced per invoice (reported ratio; WARN on violations from refunds handled separately).
- Accepted values for `currency` (EUR, USD, GBP), `subscription_status`.
- Relationship `fct_invoice_line.customer_sk → dim_customer` complete (unknown member allowed and counted).
- Source freshness ≤ 1 day.
- Schema drift on sources: none at final validation.

## 9. Expected lineage (subset)

```text
CRM.ACCOUNTS ──► stg_crm__accounts ──► int_customer_deduplicated ──► int_customer_conformed ──► snap_customer_conformed ──► dim_customer
CRM.ACCOUNT_CROSSWALK ──► stg_crm__account_crosswalk ──────────────────────────────┘
BILLING.CUSTOMERS ──► stg_billing__customers ─────────────────────────────────────┘
BILLING.INVOICES ──► stg_billing__invoices ──► fct_invoice_line ──► mart_customer_revenue_daily
BILLING.INVOICE_LINES ──► stg_billing__invoice_lines ──┘                    ▲
PAYMENTS.PAYMENTS ──► stg_payments__payments ──► int_payments_deduplicated ──► fct_payment ──┘
PRODUCT.PLANS ──► stg_product__plans ──► int_subscription_plan_history ──► dim_plan ──► fct_invoice_line
```

Column-level (examples): `fct_payment.amount ← stg_payments__payments.AMOUNT ← PAYMENTS.PAYMENTS.AMOUNT`;
`dim_customer.customer_name ← int_customer_deduplicated.account_name ← CRM.ACCOUNTS.ACCOUNT_NAME`.

## 10. Recruiter demo story (5 minutes)

1. **(0:00)** Show the request typed in plain English. Point out: no table names.
2. **(0:30)** The system asks what "revenue" means. Answer. "It knows business semantics are mine."
3. **(1:00)** Discovery + profiling panel: 13 tables found, 10 selected with reasons; duplicates 7 %, crosswalk gap 3.1 %, payment duplicates 1.5 % — all measured, not guessed.
4. **(1:45)** Design decision card: "Star schema because consumers = BI (P1); SCD2 because full history (D1)". Rule ids visible.
5. **(2:15)** Generation: 20 dbt files. Then the red event: *invalid identifier INVOICE_STATUS*. Show drift evidence and the one-line repair. Green.
6. **(3:00)** Build runs; test fails on duplicate payments; diagnosis; dedup patch; rebuild; reconciliation 0.00 %.
7. **(3:45)** Lineage graph, docs, GitHub PR link opened live.
8. **(4:15)** Click *Deploy to staging* → approval card. Approve → deployed. Show audit timeline: every model call with cost, every tool call.
9. **(4:45)** Metrics: 71 tasks, 2 automatic repairs, 2 human interventions, ~USD 2 LLM, 0.23 credits, ~13 h of manual steps automated (estimate).

Fallback: offline mode replays the same run with MOCK watermarks if live systems fail.

## 11. Generator specification

- Deterministic seed; parameters for volumes, duplicate rates, null rates, drift version.
- **Scale profiles (required before DE 004 starts).** One schema, one seed, one set of planted
  problems, three sizes selected by `--profile`:

  | Profile | Volume factor vs §2 | Approx. total rows | Purpose | Target runtime |
  |---|---|---|---|---|
  | `tiny` | ≈ 0.5 % | ≈ 35 000 | Optimized for CI: unit/integration tests, CI scenarios S01–S11, committable DuckDB fixture | fixture build < 30 s; offline demo run < 3 min |
  | `demo` | ≈ 10 % | ≈ 700 000 | Optimized for local recruiter demonstration on a laptop (DuckDB fakes) with realistic-feeling volumes | fixture build < 3 min |
  | `full` | 100 % | ≈ 6.9 M | Optimized for Snowflake scale demonstration (`COPY INTO` loader), performance/cost metrics | X-Small warehouse |

  Planted-problem *rates* (P1–P10, F1, F2) are invariant across profiles so every scenario
  behaves identically at every size; absolute counts scale. `expected/<profile>/*.json` is
  emitted per profile; evaluation baselines and recorded fixtures record the profile they
  were produced with. The volume table in §2 describes the `full` profile.
- Emits: PostgreSQL DDL + COPY-able CSV/Parquet per table per extract date; Snowflake `PUT`/`COPY INTO` loader; DuckDB fixture build for fakes.
- Two RAW states: `v1` (pre-drift) and `v2` (post-drift, plus late payments) to drive F1/F2.
- PII fields generated with Faker and flagged in a `pii_columns.yaml` used by masking tests.
- Reference expected values (`expected/*.json`: totals, counts, duplicate groups) computed by the generator for reconciliation and evaluation assertions.
