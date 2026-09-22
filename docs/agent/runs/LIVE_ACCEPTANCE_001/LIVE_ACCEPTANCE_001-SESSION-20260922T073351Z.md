# Run report — LIVE_ACCEPTANCE_001

| Field | Value |
|-------|-------|
| Task ID | LIVE_ACCEPTANCE_001 |
| Session ID | LIVE_ACCEPTANCE_001-SESSION-20260922T073351Z |
| Environment | LOCAL |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | docs/LIVE_ACCEPTANCE_001_deployed_interview |
| Base commit | b3a4291d44ee8eab32d1cc377551246e7e65c5c5 |
| Implementation commit | 9579260a23aaa0cf2de918c533b7942b2f533413 |
| Report status | SUCCESS |
| PR number | 27 |

## Goal

Determine whether the deployed Data Pilot AI Interview MVP on Railway performs the accepted behavior correctly, safely, repeatedly, and persistently. Record the verdict in evaluation reports. Do not change product code.

## Scope completed

- Fetched `main` at `b3a4291d44ee8eab32d1cc377551246e7e65c5c5`.
- Ran the offline regression suite and the requested category suites.
- Ran five authenticated Railway Interview demos, negative HTTP cases, a concurrency pair, an application restart, and a post-restart demo.
- Wrote `docs/evaluation/LIVE_ACCEPTANCE_001.md` and `docs/evaluation/DEMO_SCENARIOS_001.md`.
- Verdict: `ACCEPTED_WITH_LIMITATIONS`.

## Files changed

Created:

- `docs/evaluation/LIVE_ACCEPTANCE_001.md`
- `docs/evaluation/DEMO_SCENARIOS_001.md`
- `docs/agent/runs/LIVE_ACCEPTANCE_001/LIVE_ACCEPTANCE_001-SESSION-20260922T073351Z.md`

Modified:

- `docs/evaluation/README.md`

Removed: None

## Tests executed

- `uv run pytest -q --tb=line` against local PostgreSQL 16.14
- `uv run pytest tests/evaluation -q --tb=line`
- `uv run pytest tests/integration/interview -q --tb=line`
- `uv run pytest tests/security -q --tb=line`
- `uv run pytest tests/evaluation/test_tamper.py -q --tb=line`
- `uv run pytest tests/evaluation/test_failure_injection.py -q --tb=line`
- Persistence pytest selection listed in the acceptance report
- `uv run aide interview benchmark`
- Live HTTP checks against `https://data-pilot-ai-production.up.railway.app`

## Test results

- Full suite: 588 passed, 8 skipped, 1 failed, 0 errors, 597 tests, 2373.1s. The failure was the leakage scan hitting a gitignored local helper, not product code. A later `tests/security` run passed 6/6.
- Evaluation: 52 passed.
- Interview integration: 25 passed, 1 skipped (credential-gated live governed test).
- Tamper: 7 passed. Failure injection: 13 passed. Persistence selection: 27 passed.
- CLI benchmark: PASS.
- Live acceptance runs: 5/5 PASS. Post-restart demo: PASS.
- Negative HTTP: 401/401/400 as required. Concurrency: 409 and 200. Persistence after restart: 12/12 workflow ids remained.

Eight skipped tests are live Snowflake or live dbt checks. Details are in `docs/evaluation/LIVE_ACCEPTANCE_001.md`.

## Validation

Railway serving deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d` on commit `b3a4291`. Postgres remained deployment `a249a7c3-b47e-41fc-b8d1-496de373335f`, PostgreSQL 18.6. No secrets were printed. Product source was not modified. Synthetic expected-fixture timing drift from the generator tests was reverted and not committed.

## Errors

Full pytest exit 1 because `tests/security/test_leakage.py` scanned a gitignored helper. That file was corrected locally and is not in the commit. `railway restart` without a deployment id returned `Deployment is not restartable` because the latest deployment is `FAILED`. The serving deployment was restarted by id.

## Blockers

None

## Important decisions

- Verdict is `ACCEPTED_WITH_LIMITATIONS` because the serving loop passed and live Snowflake plus the PostgreSQL 16 claim were not fully proven on this host.
- No product defect was fixed. The failed Railway deployment is an operator follow-up.
- Railway environment name `production` was not treated as a product production action. Live payloads reported `live_smoke=NOT_RUN`.

## Architecture deviations

None

## Open questions

Why deployment `63ca238c-996f-4702-9f4e-fed91f64325c` is `FAILED` is UNKNOWN from the redacted logs. The container started and was later stopped.

## Human action required

Review and, if accepted, merge the PR. Do not merge from the agent. Optionally remove or replace the failed Railway deployment so `railway restart` targets the serving revision.

## Recommended next task

Credential-gated Snowflake live smoke on a host that already has the named secrets, after this evaluation PR is reviewed. Do not expand repair classes or architecture in that task.

## Parallel coordination

- **Declared file ownership:** `docs/evaluation/LIVE_ACCEPTANCE_001.md`, `docs/evaluation/DEMO_SCENARIOS_001.md`, `docs/evaluation/README.md`, this run report
- **Forbidden files:** `src/**`, product tests, migrations, deployment config
- **Dependencies:** MVP001–MVP004 and DEPLOY001 merged on `main`
- **Integration order:** None
