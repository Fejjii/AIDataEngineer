select
  INVOICE_ID as invoice_id,
  CUSTOMER_ID as customer_id,
  CURRENCY as currency,
  ISSUE_DATE as issue_date,
  DUE_DATE as due_date,
  INVOICE_STATUS as invoice_status,
  TOTAL_AMOUNT as total_amount
from {{ source('vantara_raw', 'invoices') }}
