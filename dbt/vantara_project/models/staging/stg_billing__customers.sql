select
  CUSTOMER_ID as customer_id,
  CUSTOMER_NAME as customer_name,
  CRM_ACCOUNT_ID as crm_account_id,
  BILLING_COUNTRY as billing_country,
  CREATED_AT as created_at,
  UPDATED_AT as updated_at
from {{ source('vantara_raw', 'customers') }}
