# Run report — LIVE_PROFILING_EFFICIENCY_002

| Field | Value |
|-------|-------|
| Task ID | LIVE_PROFILING_EFFICIENCY_002 |
| Session ID | LIVE_PROFILING_EFFICIENCY_002-SESSION-20260922T145337Z |
| Environment | LOCAL |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | `fix/live_profiling_efficiency_002` |
| Base commit | `72cf37c103cc70bad9061048bcc678eaca34cf04` |
| Implementation commit | `3e37c9cd7c8e75f3c413bd6dbd6ffae2880ac5ca` |
| Report status | SUCCESS |
| PR number | 31 |

## Goal

Make governed real Snowflake `profile_estate` finish safely below the existing 180 second gateway timeout, without weakening profiling evidence, broadening privileges, or changing repair scope.

## Scope completed

- Measured the unmodified live path before changing it.
- Reused one read-only Snowflake session for `profile_estate`.
- Stopped calling the connector `infer_relationships` handler from the profiler. That call repeated describe and inclusion work, and its candidates are not the profiling evidence.
- Reused describe metadata inside the same profile and batched per-table column aggregates into one scan. Top values stay per column so mixed types are not unioned.
- Kept `TINY_OFFLINE_BUDGET.max_seconds` at 60. Added an explicit 150 second live budget, strictly below the 180 second gateway timeout.
- Recorded phase timings on the profiler and logged only operation names and seconds.
- Converted Snowflake `Decimal` values before JSON so numeric samples can be stored.
- Pointed the live interview at fixture `v2`, matching the credentialed RAW `STATUS` column. v1 offline generation still uses `INVOICE_STATUS`.
- Kept the unknown-customer key as `varchar` so Snowflake union coercion does not null every customer surrogate.
- Quality checks `USE DATABASE AIDE_DEV` before unqualified schema names.

## Baseline timing

Unmodified `profile_estate` on the 10-table Vantara estate, measured with a diagnostic budget so the 60 second cap would not stop the breakdown. Wall clock 385.0 seconds. The run then failed while serializing a numeric sample (`Decimal`).

| Operation | Seconds |
|---|---:|
| describe_asset, profile_dataset, and key evidence | 163.0 |
| connector relationship inference (result unused) | 101.0 |
| relationship inclusion queries | 118.0 |
| sampling, then Decimal serialization failure | 2.9 |

129 Snowflake connections took 120.2 seconds. Inclusion statements were 278 queries and 121.7 seconds. Column profile and top-value statements were 92 each, about 33.6 seconds each.

## Optimized timing

Same estate through real `profile_estate`, live budget 150 seconds, gateway-style deadline 180 seconds.

| Operation | Seconds |
|---|---:|
| describe_asset | 15.0 |
| profile_dataset | 16.8 |
| key_evidence | 1.6 |
| relationship_inference | 0.0 |
| relationship_inclusion | 27.4 |
| sampling | 0.7 |
| **total** | **61.65** |

10 profiles, 62 relationships. Below 150 seconds.

## Root cause

Each warehouse call opened a new key-pair session, and the profiler also ran a second relationship pass whose output was discarded. Connection setup and repeated inclusion and column queries dominated. The 60 second offline budget stopped the governed call before that work could finish, and raising the gateway timeout was out of scope.

## Files changed

Created:

- `src/aide/connectors/snowflake/read_session.py`
- `tests/unit/connectors/test_pinned_read_session.py`
- `tests/unit/profiling/test_live_profiling_efficiency.py`
- `docs/agent/runs/LIVE_PROFILING_EFFICIENCY_002/LIVE_PROFILING_EFFICIENCY_002-SESSION-20260922T145337Z.md`

Modified:

- `src/aide/app/interview.py`
- `src/aide/app/supervisor.py`
- `src/aide/connectors/dbt/real.py`
- `src/aide/connectors/snowflake/real.py`
- `src/aide/connectors/snowflake/session.py`
- `src/aide/connectors/snowflake/sql_templates.py`
- `src/aide/generation/vantara.py`
- `src/aide/profiling/budgets.py`
- `src/aide/profiling/engine.py`
- `src/aide/profiling/masking.py`
- `tests/unit/generation/test_vantara_generation.py`
- `docs/agent/runs/README.md`

Removed: None

## Tests executed

- `uv run pytest tests/unit/profiling/test_live_profiling_efficiency.py tests/unit/connectors/test_pinned_read_session.py tests/unit/profiling/test_engine_and_phase.py tests/unit/profiling/test_masking_and_sql.py -q --tb=short`
- `uv run pytest tests/connectors/contract/test_snowflake_live.py tests/connectors/contract/test_snowflake_contract.py::test_real_live_discover_vantara_raw -o addopts=--strict-markers --tb=line -ra`
- `uv run pytest tests/connectors/contract/test_dbt_live.py -o addopts=--strict-markers --tb=line -ra`
- `uv run pytest tests/integration/interview/test_live_governed.py -o addopts=--strict-markers --tb=line -ra`
- `AIDE_TEST_DATABASE_URL=postgresql+psycopg://ubuntu@127.0.0.1:5433/aide_dev uv run pytest tests/integration/interview tests/unit/generation tests/unit/profiling -q --tb=line -m "not snowflake_live and not dbt_live"`
- `AIDE_TEST_DATABASE_URL=postgresql+psycopg://ubuntu@127.0.0.1:5433/aide_dev uv run pytest tests/evaluation tests/integration/profiling -q --tb=line -m "not snowflake_live and not dbt_live"`
- `AIDE_TEST_DATABASE_URL=postgresql+psycopg://ubuntu@127.0.0.1:5433/aide_dev uv run aide interview live-smoke --json`
- `uv run mypy` on the touched modules
- `uv run ruff check` on the touched modules

Control-plane PostgreSQL was an ephemeral container on `127.0.0.1:5433`. Port 5432 was already used by another local project and was not used. Credential values were not printed.

## Test results

- Focused profiling, session, engine, and masking tests: 27 passed.
- Live Snowflake: 5 passed, 43.67s, exit 0.
- Live dbt: 1 passed, 108.97s, exit 0.
- Governed live Interview pytest: 1 passed, 287.70s, exit 0.
- Offline Interview, generation, and profiling: 68 passed, exit 0, 276s.
- Offline evaluation and profiling integration: 54 passed, exit 0, 510s.
- `aide interview live-smoke`: PASSED, exit 0, 259s.
- mypy on touched modules: success.
- ruff on touched modules: success.

An earlier offline evaluation run failed one test with a foreign-key violation while a second pytest process used the same database. That test was rerun alone (6 passed) and the full evaluation suite was rerun after the live smoke (included in the 54 passed above).

## Validation

Live smoke detail:

`live grant metadata probe and RAW/DEV fixture reconciliation completed; governed Supervisor/Tool Gateway path exercised real Snowflake RO/DEV and real dbt without mutating VANTARA_RAW`

| Check | Result |
|---|---|
| profile_estate duration | 61.65s |
| snowflake_ro dispatch | PASS |
| snowflake_dev dispatch | PASS |
| dbt_dev dispatch | PASS |
| dbt tests | PASS |
| quality | PASS |
| reconciliation | PASS |
| least privilege | PASS (`ro_write_blocked`, `dev_raw_read_blocked`, `dev_raw_write_blocked`, `future_grants_inspected`, no grant SQL, no production or staging) |
| cleanup | PASS (live dbt test and RAW/DEV reconciliation; workflow schemas dropped after the run) |
| offline 60s budget | unchanged |
| gateway timeout | unchanged at 180s |

## Errors

None in the final validation set.

## Blockers

None.

## Important decisions

- Do not raise the gateway timeout.
- Do not drop required inclusion measurements. Remove only the unused connector relationship pass.
- Do not union top-value queries across columns. Snowflake rejected mixed timestamp and number branches.
- Live interview fixture is `v2` because credentialed `VANTARA_RAW.BILLING.INVOICES` has `STATUS`, not `INVOICE_STATUS`. Offline v1 behavior is unchanged.

## Architecture deviations

None. No new grants, no RAW mutation, no repair-scope change, no production or staging action.

## Open questions

None.

## Human action required

Review PR 31. Do not merge until that review.

## Recommended next task

None for this timeout. Merge is a human gate.

## Parallel coordination

- **Declared file ownership:** live profiling efficiency, real `profile_estate`, session reuse, live interview fixture alignment, and the tests for those paths.
- **Forbidden files:** privilege grants, repair scope, staging and production enablement.
- **Dependencies:** None.
- **Integration order:** None
