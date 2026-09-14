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
