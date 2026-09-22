# Run report — OPS_RAILWAY_FINALIZATION_001

| Field | Value |
|-------|-------|
| Task ID | OPS_RAILWAY_FINALIZATION_001 |
| Session ID | OPS_RAILWAY_FINALIZATION_001-SESSION-20260922T103200Z |
| Environment | LOCAL |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | ops/railway_finalization_001 |
| Base commit | 72cf37c103cc70bad9061048bcc678eaca34cf04 |
| Implementation commit | fd8d430b0d1fc31435c363d509588bdc48914c94 |
| Report status | SUCCESS |
| PR number | 28 |

## Goal

Close the remaining Railway operational limitations without changing product architecture: explain the failed newer deployments, make a plain restart target a valid current deployment, validate the live demo, and record PostgreSQL compatibility only if the code supports 16 and newer.

## Scope completed

- Verified origin `main` at `72cf37c103cc70bad9061048bcc678eaca34cf04`. GitHub CI run `35707761642` on that SHA completed with conclusion `success`.
- Authenticated to Railway as the existing account. Project `Data Pilot AI Demo` (`b51aaf59-f242-4c0a-8fe0-cae999fa49b7`), environment `production`, services `data pilot ai` and `Postgres`.
- Inspected deployment history. The serving release had no healthcheck. Later releases failed `/readyz` because Railway probed injected `PORT=8080` while the image listens on 8000.
- Set service variable `PORT=8000` without printing or changing secrets, then redeployed the previous image. The new deployment passed `HEALTHCHECK` and is the active and latest deployment.
- Validated `/healthz` and `/readyz`, one authenticated synthetic demo, a plain `railway restart` with no deployment id, Postgres availability, prior workflow rows, and a second demo.
- Documented PostgreSQL 16 or newer. Did not replace or downgrade the database.

## Files changed

Modified:

- `.ai/ARCHITECTURE.md`
- `README.md`
- `docs/INTERVIEW_DEMO.md`
- `docs/TECH_STACK.md`
- `docs/ops/SYNTHETIC_CLOUD_DEMO.md`

Created:

- `docs/agent/runs/OPS_RAILWAY_FINALIZATION_001/OPS_RAILWAY_FINALIZATION_001-SESSION-20260922T103200Z.md`

Removed: None

## Tests executed

- `uv run pytest tests/unit/deploy/test_synthetic_demo_packaging.py -q --tb=short`

## Test results

- Packaging tests: 12 passed, exit 0.

The full pytest suite was not re-run. GitHub CI on base `main` `72cf37c` already passed, and this change is documentation only. Compose remains `postgres:16`.

## Validation

Railway project `Data Pilot AI Demo`, environment `production`.

| Check | Result |
|---|---|
| Current serving deployment | `519df521-1d70-44c5-a8ae-f8a0af4b1854` `SUCCESS`, instance `d30b4445-0f49-4c39-b3a7-cdaa3f626654` `RUNNING`, commit `72cf37c`, image digest `sha256:7f7d88db438eb36fa5f8a45d13a9b6bf0d12a66ded9586004677a79e98499b01` |
| Failed deployment cause | `63ca238c-996f-4702-9f4e-fed91f64325c` and `0e4dd103-3191-4f8d-9ddd-686c9312f88e` built, started uvicorn on `0.0.0.0:8000`, and failed the `/readyz` healthcheck with `service unavailable`. Railway healthchecks `PORT`. The running container had `PORT=8080`. The serving deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d` had `healthcheckPath` null, so it became `SUCCESS` without that probe. |
| Replacement healthcheck | Deployment `519df521` events: `HEALTHCHECK` with no error, then `CONFIGURE_NETWORK`, then `DRAIN_INSTANCES` |
| `GET /healthz` | 200 `{"status":"ok"}` before and after restart |
| `GET /readyz` | 200 `{"status":"ok"}` before and after restart |
| Pre-restart demo | HTTP 200, `PASS`, verifier `PASS`, determinism true, evidence 100, repair count 1, human interventions 0. Workflow ids `175ea0d4-6a35-4cd7-b7aa-11e821888f3d` and `133afba6-0fc5-47fd-b4b9-2cae6add975d` |
| Plain restart | `railway restart --project b51aaf59-f242-4c0a-8fe0-cae999fa49b7 --environment production --service "data pilot ai" --yes` exit 0, returned `519df521-1d70-44c5-a8ae-f8a0af4b1854`. Logs show process shutdown and startup at 2026-09-22T10:25:40Z |
| Postgres | Deployment `a249a7c3-b47e-41fc-b8d1-496de373335f` remained `SUCCESS`. `server_version` `18.6 (Debian 18.6-1.pgdg13+2)` after restart |
| Persistence | 20 workflow rows before the first demo of this session, including prior acceptance ids `084c0aa6-96ae-4d3b-8b7a-06c399b7c7c7` and `b8832548-3dcb-427a-b616-4a8dc7e3d641`. Count was 22 after the first demo and those rows were still present after restart |
| Post-restart demo | HTTP 200, `PASS`, verifier `PASS`, determinism true, evidence 100, repair count 1, human interventions 0. Workflow ids `6e23c876-b37b-44df-956a-0b7148d79fdb` and `951f7333-ba85-452a-a2a8-bd8311b2c7b0` |

No secrets were printed. Product source, migrations, and database contents were not edited. `deploymentRemove` was not called.

## Errors

None in the Railway validation. The two earlier deployments remain `FAILED` in history and are older than the current `SUCCESS`, so they no longer make a plain restart fail.

PR 28 run `35716438823` failed before jobs started. GitHub reported: recent account payments have failed or the spending limit needs to be increased. That is not a documentation or test failure. Focused local packaging tests passed.

## Blockers

None

## Important decisions

- The healthcheck failure is a port mismatch, not an application readiness defect. `readyz` is a PostgreSQL `SELECT 1`. The container reached uvicorn before every failed probe.
- `PORT=8000` is the documented Railway workaround when the public target port is 8000 and the image does not read `PORT`. It is not a secret.
- The previous serving deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d` was not removed by `deploymentRemove`. After `519df521` passed its healthcheck, Railway drained it and its status became `REMOVED`. The replacement uses that deployment's image digest.
- PostgreSQL compatibility is documentation only. There is no `server_version` assertion. CI and Compose stay on `postgres:16`. The live database stays on 18.6. Accepted ADR DE-ADR-012 still names PostgreSQL as the only stateful service; this change does not add another datastore.

## Architecture deviations

None

## Open questions

None

## Human action required

Review and, if accepted, merge the pull request. Do not merge from the agent. Leave `PORT=8000` set on `data pilot ai`. Do not downgrade Postgres.

## Recommended next task

None for this Railway limitation. A later credential-gated Snowflake live smoke remains outside this task.

## Parallel coordination

- **Declared file ownership:** `.ai/ARCHITECTURE.md`, `README.md`, `docs/INTERVIEW_DEMO.md`, `docs/TECH_STACK.md`, `docs/ops/SYNTHETIC_CLOUD_DEMO.md`, this run report
- **Forbidden files:** `src/**`, product tests, migrations, Compose image pin, secrets
- **Dependencies:** `main` at `72cf37c103cc70bad9061048bcc678eaca34cf04`
- **Integration order:** None
