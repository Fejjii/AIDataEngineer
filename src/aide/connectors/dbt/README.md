# dbt connector (DE008A)

Transformation connector for dbt Core. The API process never holds long-lived dbt
state. Each invocation runs in an isolated working copy:

```text
.aide/work/<workflow_id>/project
```

`profiles.yml` is generated per workflow. Secret values are injected only into
the subprocess environment via `env_var(...)` references. Logs and journals
store env var **names**, never secret values.

## Instances

| Instance | Identity | Permissions | Notes |
|---|---|---|---|
| `dbt_dev` | `DEVELOPMENT` | `READ`, `DEVELOPMENT_EXECUTE`, `DEVELOPMENT_WRITE` | compile/run/test, `create_transformation`, `get_lineage` |
| `dbt_staging` | `STAGING_DEPLOY` | `STAGING_DEPLOY` | advertised only; deploy is not implemented in DE008A |

## Offline Cloud target

DE008A **adopted** real dbt Core `1.11.15` + `dbt-duckdb` 1.11.0 against Vantara
tiny DuckDB fixtures. No Snowflake credentials are used.

Live Snowflake `dbt` validation is out of this Cloud slice
(`READY_FOR_LIVE_DBT_VALIDATION`). `dbt-snowflake` 1.10+ requires
`snowflake-connector-python>=4`, which conflicts with the DE006 pin `<4`.

## Required environment variable names (Snowflake target only)

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER_DEV`
- `SNOWFLAKE_PRIVATE_KEY_DEV`
- `SNOWFLAKE_WAREHOUSE_DEV`

Missing names yield health `UNAVAILABLE` with `SECRET_UNRESOLVED:<NAME>`.

DuckDB target uses a local file path (`AIDE_DBT_DUCKDB_PATH` inside the
subprocess) and does not require secrets.

## Effect safety

Side-effecting execution (`execute_transformation`, `run_pipeline`,
`run_tests` with `store_failures=true`) is `NON_IDEMPOTENT`. DE008A does not
claim `PROVEN_CONVERGENT`.

Each attempt writes an append-only journal plus captured `manifest.json`,
`run_results.json`, compiled SQL, selected nodes, invocation arguments, and
artifact hashes.

## Reconciliation

Reconciliation reads the journal and artifacts only. Missing evidence is
`Unknown`. Authoritative absence is `NoEffect`. Running nodes are `InProgress`.
`EffectFound` requires validated artifacts/results.

## Fake

A lightweight DuckDB fake remains for unit tests: `ref`/`source` emulation,
manifest-shaped and run_results-shaped artifacts, `fail_next`, and
`fail_after_effect`.

## Fixture project

`dbt/vantara_project/` is a static connector fixture. Generated production models
are DE008B.
