# Vantara dbt project foundation (DE008A)

Static fixture project used to validate the dbt connector. It is **not** the
DE008B generated production model graph.

Models are Snowflake-portable `SELECT` statements over Vantara tiny billing
fixtures (`CUSTOMERS`, `INVOICES`) with generic `unique` / `not_null` tests.

Offline Cloud/CI target is DuckDB via `dbt-duckdb`. Live Snowflake `dbt`
validation is out of DE008A scope.
