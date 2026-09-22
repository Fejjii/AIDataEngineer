# Snowflake live validation — SNOWFLAKE_LIVE_001

**Verdict:** `REMEDIATION_REQUIRED`

**Date:** 2026-09-22  
**Repository:** Fejjii/AIDataEngineer  
**Base:** `origin/main` `72cf37c103cc70bad9061048bcc678eaca34cf04`  
**Branch:** `eval/snowflake_live_001`  
**PR:** 29  
**Host:** Local Mac  
**Product code changes:** none  
**Warehouse privilege changes:** none  
**Production or staging actions:** none

The six required environment variable names were present in the local gitignored env file and absent from the process environment before the run. Values were never printed. No new Snowflake grants were created.

Control-plane PostgreSQL for the governed path was an ephemeral PostgreSQL 16.14 container on `127.0.0.1:5433`, database `aide_dev`. Port 5432 was already in use by another local project and was not used.

## Overall verdict

`REMEDIATION_REQUIRED`

Live Snowflake connector tests, the live dbt test, and the grant/reconciliation probe passed. The governed Interview live smoke did not. `profile_estate` on the real RO identity exceeded the offline profiling budget (`max_seconds=60`, observed `70.719s`) and was classified `RESOURCE_LIMIT`. The workflow failed in `PROFILING`. `snowflake_dev` and `dbt_dev` were never dispatched, so the gateway path did not reach DEV writes, dbt parse/compile/run/tests, or quality checks.

## Live tests result

Previously skipped credential-gated tests: **7 passed, 1 failed, 0 skipped**.

| Suite | Command | Result |
|---|---|---|
| Live Snowflake | `uv run pytest tests/connectors/contract/test_snowflake_live.py tests/connectors/contract/test_snowflake_contract.py::test_real_live_discover_vantara_raw -o addopts='--strict-markers' --tb=line -ra` | **5 passed, 0 failed, 0 skipped**, 107.53s, exit 0 |
| Live dbt | `uv run pytest tests/connectors/contract/test_dbt_live.py -o addopts='--strict-markers' --tb=line -ra` | **1 passed, 0 failed, 0 skipped**, 135.59s, exit 0 |
| Live probe plus governed pytest | `uv run pytest tests/connectors/contract/test_interview_live_smoke.py tests/integration/interview/test_live_governed.py -o addopts='--strict-markers' --tb=short -ra` | **1 passed, 1 failed, 0 skipped**, 203.03s, exit 1 |

| Test | Result | Time |
|---|---|---:|
| `test_live_ro_health_role_and_discovery` | passed | 28.416s |
| `test_live_ro_describe_profile_sample_relationships_and_query` | passed | 59.461s |
| `test_live_deadline_timeout` | passed | 0.002s |
| `test_live_dev_namespace_write_reject_reconcile_and_cleanup` | passed | 15.873s |
| `test_real_live_discover_vantara_raw` | passed | 3.106s |
| `test_live_dbt_snowflake_debug_parse_compile_run_test_isolate_fail_cleanup` | passed | 134.609s |
| `test_at18_at19_at24_live_interview_smoke` | passed | 44.789s |
| `test_at24_governed_live_interview_uses_tool_gateway` | failed | 156.773s |

## Governed smoke result

**FAIL.** Exit code 1.

`uv run aide interview live-smoke --json` returned `status=FAILED`.

The grant probe inside that command passed, and the continuation through InterviewSupervisor failed before DEV and dbt dispatch. Reported detail:

`gateway did not dispatch required connectors: ['dbt_dev', 'snowflake_dev']`

Persisted control-plane rows for the pytest failure, and the same shape on the CLI rerun:

| Field | Observed |
|---|---|
| Workflow state | `FAILED` |
| Failure phase | `PROFILING` |
| `profile_estate` classification | `RESOURCE_LIMIT` |
| Gateway connector ids | `snowflake_ro` only |
| `discover_assets` / `describe_asset` | succeeded |
| `snowflake_dev` intents | 0 |
| `dbt_dev` intents | 0 |
| `tests_ok` | false |
| `quality_ok` | false |
| `grant_sql_executed` | false |
| `production_or_staging_action` | false |
| `include_schema_drift` | false |
| Independent Verifier on the live path | not run |

A direct call to `RealSnowflakeConnector.profile_estate` with the Interview selected assets and `fixture_version="v1"` raised `ProfilingBudgetExceeded` / `FailureClass.RESOURCE_LIMIT` with message `max_seconds=60 exceeded (70.719s)`. That budget is `TINY_OFFLINE_BUDGET` in `src/aide/profiling/budgets.py`. The gateway template timeout for `profile_estate` is 180 seconds, so the 60 second profiler budget fails first.

`_assess_governed_live` reports missing connectors before the workflow failure reason, so the smoke detail hides `RESOURCE_LIMIT`.

## dbt result

**PASS** on the standalone live dbt test.

`test_live_dbt_snowflake_debug_parse_compile_run_test_isolate_fail_cleanup` passed in 134.609s. That test asserts dbt debug, parse, compile, run, and tests, workflow-scoped `AIDE_DEV` schemas, DEV denial of `VANTARA_RAW`, reconciliation `EffectFound` with `ok=True`, a deterministic compile failure classified `DBT_COMPILE`, and schema cleanup.

**NOT REACHED** on the governed Interview path. `dbt_dev` had no dispatch intents.

## Least privilege result

**PASS** for the identities exercised. No grants were issued.

| Check | Result | Evidence |
|---|---|---|
| RO identity can inspect authorized RAW metadata | PASS | RO health, discovery, describe, profile, sample, and the live probe `ro_inspected_raw=true` |
| RO cannot mutate RAW | PASS | Live probe `ro_write_blocked=true`; write prohibition comes from grant metadata, not RAW DML |
| DEV identity writes only allowed `AIDE_DEV` objects | PASS | `test_live_dev_namespace_write_reject_reconcile_and_cleanup`; probe `dev_scope_aide_dev=true` |
| No broad RAW write privilege | PASS | Probe `dev_raw_read_blocked=true` and `dev_raw_write_blocked=true`; DEV `SELECT` on `VANTARA_RAW.BILLING.INVOICES` denied inside the live dbt test |
| Gateway remains the execution boundary | PARTIAL | Governed path dispatched only through the gateway, and only `snowflake_ro` ran before profiling failed |
| Production disabled | PASS | Probe `production_or_staging_action=false`; live connector allow lists stay on DEV |
| Staging disabled | PASS | Same probe flag and allow lists; `include_schema_drift=false` |
| `grant_sql_executed` | false | Probe and CLI |

## Cleanup result

**PASS** for objects the live dbt test created. **LIMITED** for the DEV namespace test schema.

The live dbt test asserts both workflow `WF*_DBT` schemas are dropped. After the run, `AIDE_DEV` had no `WF*_DBT` schemas.

The DEV namespace test dropped its probe table and left one empty schema created during this run:

| Schema | Created | Tables |
|---|---|---:|
| `WF7AFBEB_LIVE` | 2026-09-22T03:25:10-07:00 | 0 |

Six other empty `WF*_LIVE` schemas already existed from 2026-09-13 and 2026-09-14. They were not dropped. This task did not broaden cleanup and did not drop pre-existing objects.

The failed governed workflow stopped in profiling and did not create a DEV workflow schema.

## Reconciliation result

**PASS** on the paths that ran.

The live probe asserts `raw_dev_reconciled=true`. The live dbt test asserts `EffectFound` with `ok=True` after `dbt run`, and `EffectFound` with `ok=False` after the injected compile failure. The governed path did not reach transformation reconciliation.

## Defects

One product defect. No product code was changed.

**Governed live Interview smoke fails in profiling before DEV and dbt.**

| Field | Value |
|---|---|
| Severity | High for the credentialed Interview live smoke. Offline MVP behavior was not re-run and is unchanged. Standalone live Snowflake and live dbt tests passed |
| Reproduction | On a host with `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER_RO`, `SNOWFLAKE_PRIVATE_KEY_RO`, `SNOWFLAKE_USER_DEV`, `SNOWFLAKE_PRIVATE_KEY_DEV`, and `SNOWFLAKE_WAREHOUSE_DEV` set, run `uv run pytest tests/integration/interview/test_live_governed.py` or `uv run aide interview live-smoke` |
| Expected | `LiveSmokeStatus.PASSED`. Gateway dispatches `snowflake_ro`, `snowflake_dev`, and `dbt_dev`. dbt parse, compile, run, and tests succeed. DEV writes stay in workflow-scoped `AIDE_DEV` |
| Actual | Workflow `FAILED` in `PROFILING`. `profile_estate` raised `RESOURCE_LIMIT` because `TINY_OFFLINE_BUDGET.max_seconds` is 60 and the live call took 70.719s. Dispatch connector ids were only `snowflake_ro`. Smoke detail was `gateway did not dispatch required connectors: ['dbt_dev', 'snowflake_dev']`. CLI exit code 1 |
| Affected capability | Governed live Interview path: Supervisor to Tool Gateway to real DEV Snowflake and real dbt. RO inspection, least privilege, and standalone dbt against `AIDE_DEV` still passed |

## Recommended next action

Human review of this evaluation PR. Do not merge it as a product fix.

A follow-up remediation task should make live `profile_estate` finish inside the gateway timeout (the template already allows 180 seconds) and should report `RESOURCE_LIMIT` as the smoke failure instead of only the connectors that never ran. Do not add `VANTARA_RAW` privileges. Do not change repair scope. Do not enable production or staging.
