# Snowflake connector (DE 005)

Warehouse connector for Snowflake. Policy and the SQL classifier remain the
non-bypassable safety boundary. This package enforces identity, allow-lists, DEV
namespace isolation, statement timeouts, canonical query tags, and `AUTOCOMMIT=TRUE`
as defence in depth.

## Identities

| Instance | Identity class | Role | Capabilities |
|---|---|---|---|
| `snowflake_ro` | `READ_ONLY` | `AIDE_DEV_RO` | discover, describe, drift, profile, sample, infer, validate, execute, metrics |
| `snowflake_dev` | `DEVELOPMENT` | `AIDE_DEV_RW` | `create_dataset`, `drop_dataset` only (`READ` is not advertised) |

`snowflake_dev` must not advertise or execute READ capabilities.

## Required environment variable names

Values are never logged, printed, or stored on `SecretRef` settings objects.

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER_DEV`
- `SNOWFLAKE_PRIVATE_KEY_DEV`
- `SNOWFLAKE_WAREHOUSE_DEV`

Optional:

- `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`

Missing required names produce health status `UNAVAILABLE` with reason
`SECRET_UNRESOLVED:<ENV_VAR_NAME>`.

## Session defaults

- `STATEMENT_TIMEOUT_IN_SECONDS` from the task deadline
- `AUTOCOMMIT = TRUE`
- Canonical `QUERY_TAG = aide:v1;wf=<uuid>;phase_run=<uuid>;task=<uuid>;op=<64-hex>;attempt=<uuid>;n=<int>`

## DEV namespace

Writes must target `AIDE_DEV.<WORKFLOW_SHORT_ID>_*` where
`WORKFLOW_SHORT_ID = WF` + the first 6 hex characters of the workflow UUID.

## Health CLI

```bash
uv run aide connectors check --json
```

Prints connector id, fake/real flag, status, and reason codes. Secret values are never
printed.

## Tests

Fake contract tests run in Cloud/CI. Real vendor tests skip when the required
environment variables are unset. Live Snowflake validation is DE 005B.
