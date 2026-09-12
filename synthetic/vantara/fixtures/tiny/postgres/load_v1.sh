#!/usr/bin/env bash
# Load Vantara synthetic CSV fixtures into PostgreSQL (profile=tiny, version=v1)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CSV_ROOT="${ROOT}/fixtures/tiny/v1/csv"
PSQL="${PSQL:-psql}"

psql "${DATABASE_URL:?DATABASE_URL is required}" -f "${ROOT}/postgres/ddl_v1.sql"

copy_table() {
  local schema="$1" table="$2" file="$3"
  ${PSQL} "${DATABASE_URL}" -c \
    "\copy ${schema}.${table} FROM '${CSV_ROOT}/${file}' CSV HEADER"
}

copy_table vantara_crm accounts crm/accounts.csv
copy_table vantara_crm contacts crm/contacts.csv
copy_table vantara_crm opportunities crm/opportunities.csv
copy_table vantara_crm account_crosswalk crm/account_crosswalk.csv
copy_table vantara_billing customers billing/customers.csv
copy_table vantara_billing subscriptions billing/subscriptions.csv
copy_table vantara_billing invoices billing/invoices.csv
copy_table vantara_billing invoice_lines billing/invoice_lines.csv
copy_table vantara_payments payments payments/payments.csv
copy_table vantara_payments refunds payments/refunds.csv
copy_table vantara_product plans product/plans.csv
copy_table vantara_support tickets support/tickets.csv
