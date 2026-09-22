# Run report — LIVE_PROFILING_REMEDIATION_001

| Field | Value |
|-------|-------|
| Task ID | LIVE_PROFILING_REMEDIATION_001 |
| Session ID | LIVE_PROFILING_REMEDIATION_001-SESSION-20260922T125442Z |
| Environment | LOCAL |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | `fix/live_profiling_budget_001` |
| Base commit | `72cf37c103cc70bad9061048bcc678eaca34cf04` |
| Implementation commit | `631f45e145ff3eb359b6016a9633476532e07571` |
| Report status | FAILED |
| PR number | 30 |

## Goal

Make governed live Snowflake `profile_estate` finish inside an explicit budget that stays below the 180 second gateway timeout, without changing the offline 60 second budget, privileges, or repair scope.

## Scope completed

- Left `TINY_OFFLINE_BUDGET.max_seconds` at 60.
- Added `LIVE_SNOWFLAKE_PROFILING_BUDGET` at 150 seconds. Query, sample, and pair caps match the offline budget.
- The real Snowflake connector takes that budget as an explicit constructor argument and refuses a budget that is not strictly below the `profile_estate` gateway timeout.
- Real `profile_estate` passes the gateway `CallContext` into the profiler so statement deadlines follow the gateway deadline instead of the engine's offline 120 second fallback.
- Governed live smoke detail now leads with the workflow failure, including `RESOURCE_LIMIT`, and then mentions connectors that never ran.
- Offline evaluation and Interview regressions passed.
- Live Snowflake tests and the live dbt test passed.
- The governed live Interview pytest failed. `aide interview live-smoke` was not run after that failure.

## Files changed

Created:

- `tests/unit/app/test_governed_live_diagnostics.py`
- `tests/unit/profiling/test_live_profiling_budget.py`
- `docs/agent/runs/LIVE_PROFILING_REMEDIATION_001/LIVE_PROFILING_REMEDIATION_001-SESSION-20260922T125442Z.md`

Modified:

- `src/aide/app/interview.py`
- `src/aide/connectors/snowflake/real.py`
- `src/aide/profiling/budgets.py`
- `src/aide/profiling/engine.py`
- `docs/agent/runs/README.md`

Removed: None

## Tests executed

- `uv run pytest tests/unit/profiling/test_live_profiling_budget.py tests/unit/app/test_governed_live_diagnostics.py tests/unit/profiling/test_engine_and_phase.py -q --tb=short`
- `AIDE_TEST_DATABASE_URL=postgresql+psycopg://ubuntu@127.0.0.1:5433/aide_dev uv run pytest tests/integration/interview tests/evaluation tests/integration/profiling tests/unit/profiling -q --tb=line -m "not snowflake_live and not dbt_live"`
- `uv run ruff check` and `uv run mypy` on the touched modules
- `uv run lint-imports`
- `uv run pytest tests/connectors/contract/test_snowflake_live.py tests/connectors/contract/test_snowflake_contract.py::test_real_live_discover_vantara_raw -o addopts=--strict-markers --tb=line -ra`
- `uv run pytest tests/connectors/contract/test_dbt_live.py -o addopts=--strict-markers --tb=line -ra`
- `uv run pytest tests/integration/interview/test_live_governed.py -o addopts=--strict-markers --tb=line -ra` (twice)

Control-plane PostgreSQL was an ephemeral container on `127.0.0.1:5433`. Port 5432 was already used by another local project and was not used. Credential values were not printed.

## Test results

- Focused budget and diagnostics tests: passed (29).
- Offline Interview, evaluation, profiling integration, and profiling unit tests: passed (120), exit 0, 883s.
- Import contracts: 13 kept.
- Live Snowflake: 5 passed, 0 failed, 73.31s, exit 0.
- Live dbt: 1 passed, 0 failed, 128.71s, exit 0.
- Governed live Interview pytest, final run: 1 failed, 348.72s, exit 1.
- `aide interview live-smoke`: not run.

## Validation

The final governed pytest detail was:

`RESOURCE_LIMIT; gateway did not dispatch required connectors: ['dbt_dev', 'snowflake_dev']`

Control-plane audit for that attempt:

| Event | Time (UTC) |
|---|---|
| `GATEWAY_DISPATCH_INTENT` `profile_estate` | 2026-09-22 12:32:19.925 |
| `GATEWAY_FAILED` `RESOURCE_LIMIT` | 2026-09-22 12:36:27.549 |

Wall clock for that single `profile_estate` attempt: 247.6 seconds. No `snowflake_dev` or `dbt_dev` dispatch was recorded. Workflow state was `FAILED`.

An earlier governed attempt on the 150 second budget, before the gateway context was forwarded, failed in 240.10s with `TIMEOUT` because the profiler still used its own 120 second `CallContext`.

## Errors

`profile_estate` still does not finish under a budget that is allowed to stay below the 180 second gateway timeout.

SNOWFLAKE_LIVE_001 reported 70.719 seconds. That was the moment the 60 second offline check fired, not a completed profile. After the live cap was raised to 150 seconds, the same governed call continued and was stopped at 247.6 seconds with `RESOURCE_LIMIT`. The budget check runs between warehouse calls, so the in-flight call returned after both the 150 second profiler cap and the 180 second gateway deadline.

A live budget large enough to cover 247.6 seconds would be above the 180 second gateway timeout. That change is outside this task.

## Blockers

Governed live smoke remains failed. Completing real Snowflake profiling needs either less profiling work or a gateway timeout above the observed 247.6 seconds. This task must not raise the gateway timeout and must not raise the profiler budget to meet or exceed 180 seconds.

## Important decisions

- Do not change `TINY_OFFLINE_BUDGET`.
- Live budget is an explicit real-connector argument, not an environment probe.
- 150 seconds is the live cap because it is above the 70.719 second failure point and below 180 seconds.
- Stop after the second governed failure instead of raising the cap again.

## Architecture deviations

None. No privilege, repair, staging, or production changes.

## Open questions

None. The remaining failure is the profile duration, not an unknown exception.

## Human action required

Review the PR. Do not merge it as a completed live-smoke fix. A follow-up has to make full `profile_estate` finish in under 180 seconds without raising the gateway timeout or adding RAW privileges.

## Recommended next task

Reduce the real Snowflake profiling work, or interrupt the in-flight warehouse call when the live budget or the gateway deadline is reached, so `profile_estate` cannot run for 247.6 seconds. Then rerun the governed live smoke. Do not add `VANTARA_RAW` grants.

## Parallel coordination

- **Declared file ownership:** profiling budget, real `profile_estate`, governed live smoke detail, and the tests for those paths.
- **Forbidden files:** privilege grants, repair scope, staging and production enablement.
- **Dependencies:** SNOWFLAKE_LIVE_001 evidence. No product merge required.
- **Integration order:** None
