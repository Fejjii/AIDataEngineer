select
  INVOICE_ID as invoice_id,
  CUSTOMER_ID as customer_id,
  CURRENCY as currency,
  ISSUE_DATE as issue_date,
  DUE_DATE as due_date,
  {% if target.type == 'snowflake' %}
  STATUS as invoice_status,
  {% else %}
  INVOICE_STATUS as invoice_status,
  {% endif %}
  TOTAL_AMOUNT as total_amount
from {{ source('vantara_raw', 'invoices') }}
