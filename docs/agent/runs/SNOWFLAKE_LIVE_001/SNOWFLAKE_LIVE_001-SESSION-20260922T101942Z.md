# Run report — SNOWFLAKE_LIVE_001

| Field | Value |
|-------|-------|
| Task ID | SNOWFLAKE_LIVE_001 |
| Session ID | SNOWFLAKE_LIVE_001-SESSION-20260922T101942Z |
| Environment | LOCAL |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | `eval/snowflake_live_001` |
| Base commit | `72cf37c103cc70bad9061048bcc678eaca34cf04` |
| Implementation commit | `ef0c406d2d51af0c9f6e0ffc81db92b67069c37f` |
| Report status | REVIEW_REQUIRED |
| PR number | 29 |

## Goal

Run the credential-gated real Snowflake and dbt validation for the accepted Interview MVP. Record the verdict. Do not change product code, grants, or repair scope.

## Scope completed

Confirmed the six required environment variable names were present locally and did not print values. Ran the existing live Snowflake tests, the live dbt test, the previously skipped credential-gated tests, and the governed Interview live smoke. Recorded pass, fail, and skip counts. Documented one profiling defect. Did not broaden grants or modify production data.

## Files changed

Created: `docs/evaluation/SNOWFLAKE_LIVE_001.md`, this report

Modified: `docs/evaluation/README.md`, `docs/agent/runs/README.md`

Removed: None

## Tests executed

- `uv run pytest tests/connectors/contract/test_snowflake_live.py tests/connectors/contract/test_snowflake_contract.py::test_real_live_discover_vantara_raw -o addopts='--strict-markers' --tb=line -ra`
- `uv run pytest tests/connectors/contract/test_dbt_live.py -o addopts='--strict-markers' --tb=line -ra`
- `uv run pytest tests/connectors/contract/test_interview_live_smoke.py tests/integration/interview/test_live_governed.py -o addopts='--strict-markers' --tb=short -ra`
- `uv run aide interview live-smoke --json`

## Test results

Previously skipped credential-gated tests: **7 passed, 1 failed, 0 skipped**.

| Suite | Result |
|---|---|
| Live Snowflake | 5 passed, 0 failed, 0 skipped, 107.53s, exit 0 |
| Live dbt | 1 passed, 0 failed, 0 skipped, 135.59s, exit 0 |
| Live probe | 1 passed, 44.789s |
| Governed pytest | 1 failed, 156.773s, suite exit 1 |
| `aide interview live-smoke` | exit 1, `status=FAILED` |

Control plane was ephemeral PostgreSQL 16.14 on `127.0.0.1:5433`. Port 5432 was not used.

## Validation

| Check | Result |
|---|---|
| RO inspects authorized RAW metadata | PASS |
| RO cannot mutate RAW | PASS |
| DEV writes only allowed `AIDE_DEV` objects | PASS |
| No broad RAW write privilege | PASS |
| Gateway execution boundary | PARTIAL — only `snowflake_ro` dispatched before profiling failed |
| Production disabled | PASS |
| Staging disabled | PASS |
| dbt parse, compile, run, tests | PASS on the standalone live dbt test; not reached on the governed path |
| Cleanup | PASS for `WF*_DBT` schemas; one empty `WF7AFBEB_LIVE` schema left by the DEV namespace test |
| Reconciliation | PASS on the probe and standalone dbt test; not reached on the governed path |
| Live smoke | FAIL |

Evaluation verdict: `REMEDIATION_REQUIRED`.

## Errors

`profile_estate` raised `ProfilingBudgetExceeded` / `RESOURCE_LIMIT`: `max_seconds=60 exceeded (70.719s)`. The governed smoke then reported missing `dbt_dev` and `snowflake_dev` dispatches.

## Blockers

None for recording the evaluation. The governed live path needs a product remediation before it can pass. That fix is outside this task.

## Important decisions

No grants were added. No product code was changed. The offline 60 second profiling budget is what failed the live smoke; the gateway template timeout is 180 seconds.

## Architecture deviations

None

## Open questions

None

## Human action required

Review the evaluation PR. Do not merge it as a product fix. Schedule a remediation that lets live profiling finish and that reports `RESOURCE_LIMIT` directly. Do not grant `AIDE_DEV_RW` any new `VANTARA_RAW` privilege.

## Recommended next task

Remediate live `profile_estate` budget handling for the governed Interview smoke, then rerun `SNOWFLAKE_LIVE_001` checks.

## Parallel coordination

- **Declared file ownership:** `docs/evaluation/SNOWFLAKE_LIVE_001.md`, `docs/evaluation/README.md`, `docs/agent/runs/SNOWFLAKE_LIVE_001/SNOWFLAKE_LIVE_001-SESSION-20260922T101942Z.md`, `docs/agent/runs/README.md`
- **Forbidden files:** `src/**`, product tests, grant SQL, repair scope
- **Dependencies:** accepted Interview MVP on `main` `72cf37c`
- **Integration order:** None
