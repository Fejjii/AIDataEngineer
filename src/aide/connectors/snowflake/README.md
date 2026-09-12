# Snowflake connector (DE 005)

Warehouse connector for Snowflake. Policy and the SQL classifier remain the
non-bypassable safety boundary. This package enforces identity, allow-lists, DEV
namespace isolation, statement timeouts, canonical query tags, and `AUTOCOMMIT=TRUE`
as defence in depth.

## Identities

| Instance | Identity class | Role | Credentials | Capabilities |
|---|---|---|---|---|
| `snowflake_ro` | `READ_ONLY` | `AIDE_DEV_RO` | `SNOWFLAKE_USER_RO`, `SNOWFLAKE_PRIVATE_KEY_RO` | discover, describe, drift, profile, sample, infer, validate, execute, metrics |
| `snowflake_dev` | `DEVELOPMENT` | `AIDE_DEV_RW` | `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV` | `create_dataset`, `drop_dataset` only (`READ` is not advertised) |

`snowflake_dev` must not advertise or execute READ capabilities. READ_ONLY and
DEVELOPMENT identities use **separate** Snowflake users and private keys.

## Required environment variable names

Values are never logged, printed, or stored on `SecretRef` settings objects.

Shared:

- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_WAREHOUSE_DEV`

READ_ONLY (`snowflake_ro`):

- `SNOWFLAKE_USER_RO`
- `SNOWFLAKE_PRIVATE_KEY_RO`

DEVELOPMENT (`snowflake_dev`):

- `SNOWFLAKE_USER_DEV`
- `SNOWFLAKE_PRIVATE_KEY_DEV`

Optional:

- `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE`

Missing required names produce health status `UNAVAILABLE` with reason
`SECRET_UNRESOLVED:<ENV_VAR_NAME>`.

## Allow list

`snowflake_ro` may touch `VANTARA_RAW` (accepted Vantara demo source), `RAW`
(compatibility with existing fake/offline tests), and `AIDE_DEV`.
`snowflake_dev` may touch `AIDE_DEV` only.

DE005B live discovery must target `VANTARA_RAW`.

## Health

Health runs `SELECT CURRENT_ROLE()` and fails closed unless the authenticated role
matches the connector identity:

- `snowflake_ro` → `AIDE_DEV_RO`
- `snowflake_dev` → `AIDE_DEV_RW`

A mismatch returns status `UNAVAILABLE` with reason code `ROLE_MISMATCH` and is
never `AVAILABLE`.

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
READ_ONLY environment variables are unset. Live Snowflake validation is DE 005B
and discovers `VANTARA_RAW`.
