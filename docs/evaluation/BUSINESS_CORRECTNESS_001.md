# BUSINESS_CORRECTNESS_001

Independent expectations come from `aide.quality.business_oracle`, which reads
the committed tiny CSV fixtures and does not use generated mart SQL.

Verdict: **BUSINESS_CORRECTNESS_PASS**

## Contract

| Rule | Expectation |
|---|---|
| Currency | `eur` and `€` become EUR. USD and GBP stay themselves. No FX conversion. |
| Grain | One row per `customer_sk`, `date_day`, `currency`. |
| Invoiced | Sum of invoice line amount by customer, invoice issue date, invoice currency. |
| Paid | Sum of one surviving payment per `invoice_id` + `payment_ref`, by customer, payment date, invoice currency. Survivor is latest `_LOADED_AT`, then lowest `payment_id`. |
| Refunded | Sum of refund amount by customer, refund date, invoice currency. The refund joins the payment id it names, including a payment row that lost deduplication. |
| Net paid | `paid_amount - refunded_amount` on that same grain. |
| Deleted CRM | `is_deleted` accounts do not survive website-domain deduplication. |
| Unknown customer | Unresolved billing customer `-1` uses `md5('-1')`. |

`customer_sk` for a resolved billing customer is `md5` of the customer id text.
Payment and refund dates are the UTC calendar date of the source timestamp.

## Independent expected currency totals

### v1

| Currency | Invoiced | Paid | Refunded | Net paid |
|---|---:|---:|---:|---:|
| EUR | 25094328.94 | 5362127.38 | 47192.11 | 5314935.27 |
| GBP | 7928884.04 | 1658073.92 | 22237.22 | 1635836.70 |
| USD | 17157019.21 | 3567843.39 | 34017.80 | 3533825.59 |

Other v1 expectations: 11816 mart rows, 5650 payments all surviving, 190 refunds,
0 refunds on dropped payments, 25 invoices for customer `-1`, deleted CRM
accounts `4b6a98a4-09a3-5595-9b79-c7aeb3a438cb` and
`c11c4ace-908b-5a9c-8050-10bc6033ca10` absent from survivors.

### v2

Invoice totals match v1. Payment source rows are 5735 and survivors stay 5650.
85 refunds reference a dropped duplicate payment and still count.

| Currency | Invoiced | Paid | Refunded | Net paid |
|---|---:|---:|---:|---:|
| EUR | 25094328.94 | 5362127.38 | 52249.22 | 5309878.16 |
| GBP | 7928884.04 | 1658073.92 | 18296.11 | 1639777.81 |
| USD | 17157019.21 | 3567843.39 | 32453.93 | 3535389.46 |

v2 mart rows: 11818.

## Before

The pre-change mart columns were `customer_sk`, `date_day`, `invoiced_amount`,
`paid_amount`. A v1 build produced 11341 rows. `fct_invoice_line` had 40665
rows against 20500 source lines because each plan code joined every plan
version. That inflated invoiced amount to 98831749.44, against the source line
sum 50180232.19. Refunds were staged and absent from the mart. The two deleted
CRM accounts have a later `updated_at` than their non-deleted siblings, and the
old survivorship rule kept them. Quality checks compared the mart to those same
facts, so internal reconciliation could pass.

| Assertion | Before |
|---|---|
| Currency isolation | FAIL |
| Invoice totals by currency | FAIL |
| Refund totals | FAIL |
| Net paid | FAIL |
| Grain includes currency | FAIL |
| Deleted CRM excluded | FAIL |
| Unknown customer member | PASS for customer `-1` via the existing dimension row |
| Duplicate payment key | PASS on the existing `invoice_id` + `payment_ref` rule |

## Corrections

- Normalize and group the mart by invoice currency.
- Add `refunded_amount` and `net_paid_amount`.
- Exclude `is_deleted` CRM accounts before domain survivorship.
- Keep one current plan row per `plan_code` on `fct_invoice_line`.
- Carry invoice currency on `fct_payment`.
- Send unresolved customers to `md5('-1')`.
- Quality checks recompute invoice, payment, and refund totals from staging,
  and still keep the fact-to-mart sum checks.

## After

`tests/unit/quality/test_business_correctness.py` builds the generated models
on v1 and v2 and compares every mart row to the oracle. Every assertion PASS.

Generated mart columns are now `customer_sk`, `date_day`, `currency`,
`invoiced_amount`, `paid_amount`, `refunded_amount`, `net_paid_amount`.

The benchmark fingerprint changes because generated SQL, quality check ids, and
the validation column list changed. The schema-drift repair is still exactly
`INVOICE_STATUS` to `STATUS`, once, with no recursive repair.

## Remaining limitations

- No FX conversion and no rate table.
- Open amount, active subscriptions, and MRR are not calculated.
- Customer and plan history tables are still current-row shapes, not full SCD2.
- The recorded modelling proposal grain is still customer and day. Executed SQL
  is the business contract.
- The offline interview loads v1 payments, which contain no duplicate payment
  keys. v2 duplicate and dropped-payment refund behavior is covered by the
  oracle test, not by the schema-drift scenario itself.
