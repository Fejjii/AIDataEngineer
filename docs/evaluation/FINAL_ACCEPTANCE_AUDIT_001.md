# Final acceptance audit — FINAL_ACCEPTANCE_AUDIT_001

**Verdict:** `ACCEPTED_WITH_LIMITATIONS`

**Date:** 2026-09-22  
**Repository:** Fejjii/AIDataEngineer  
**Task:** FINAL_ACCEPTANCE_AUDIT_001  
**Audited SHA:** `main` `0425d3248ceb144043821941f2fef3d2dc370e58`  
**Branch:** `audit/final_acceptance_001`  
**Product code changes:** none  
**Defects fixed:** none (none found)

This is an independent read-first, test-second, report-last acceptance audit of
Data Pilot AI. It does not add product features, redesign architecture, change
grants, or expand repair scope.

Open PR 28 (`ops/railway_finalization_001`, head `d0b4b0d`) was inspected as
documentation reconciliation only. It is not merged and was not used as the
implementation under test.

## Overall verdict

`ACCEPTED_WITH_LIMITATIONS`

The Interview MVP on `0425d32` performs the accepted closed loop offline and on
the deployed Railway synthetic demo. Credentialed Snowflake RO/DEV, live dbt,
governed Interview, and `aide interview live-smoke` all PASSED on this host.
Plain `railway restart` now targets the serving SUCCESS deployment. No product
defect was found.

Limitations that keep the verdict from a bare `ACCEPTED`:

- Tracked `main` docs still say exclusive PostgreSQL 16. Offline used 16.14.
  Railway is live-validated on PostgreSQL 18.6. The application does not assert
  `server_version`. PR 28 records the supported requirement as PostgreSQL 16 or
  newer and is not yet merged.
- Successful Interview rows remain `workflows.state=VALIDATION` while the HTTP
  demo status is `VERIFIED`. Existing tests allow `VALIDATION` or `COMPLETED`.
- Live Snowflake does not inject RAW drift and does not run the Independent
  Verifier. That is the accepted live contract, not a failed test.
- Interview MVP scope remains one request and one allow-listed repair class.

Recommended freeze: **Interview MVP freeze.** Merge PR 28 for documentation
truth. Do not add connectors, repair classes, grants, or architecture.

## Test counts

| Suite | Command | Result |
|---|---|---|
| Full non-live regression | `uv run pytest -q --tb=line -m "not snowflake_live and not dbt_live"` | **598 passed, 0 failed, 0 skipped, 0 errors**, 2345.4s, exit 0 |
| Evaluation | `uv run pytest tests/evaluation -q --tb=line` | **52 passed**, 469.6s, exit 0 |
| Interview integration | `uv run pytest tests/integration/interview -q --tb=line -m "not snowflake_live and not dbt_live"` | **25 passed**, 155.6s, exit 0 |
| Tamper | `uv run pytest tests/evaluation/test_tamper.py -q --tb=line` | **7 passed**, 4.5s, exit 0 |
| Failure injection | `uv run pytest tests/evaluation/test_failure_injection.py -q --tb=line` | **13 passed**, 219.4s, exit 0 |
| Persistence | evaluation persistence plus interview restart, evidence, verifier, and repair-budget tests | **27 passed**, 133.1s, exit 0 |
| Deterministic benchmark | `uv run aide interview benchmark` | **PASS**, exit 0, wall clock 29323 ms MEASURED |
| Live Snowflake connector | `uv run pytest tests/connectors/contract/test_snowflake_live.py tests/connectors/contract/test_snowflake_contract.py::test_real_live_discover_vantara_raw -o addopts=--strict-markers` | **5 passed**, 62.5s, exit 0 |
| Live dbt | `uv run pytest tests/connectors/contract/test_dbt_live.py -o addopts=--strict-markers` | **1 passed**, 147.0s, exit 0 |
| Governed live Interview | `uv run pytest tests/integration/interview/test_live_governed.py -o addopts=--strict-markers` | **1 passed**, 293.3s, exit 0 |
| Interview live smoke | `uv run aide interview live-smoke --json` | **PASSED**, exit 0 |

Local control-plane database: ephemeral PostgreSQL **16.14** on
`127.0.0.1:5433` (offline / category / benchmark) and `127.0.0.1:5434` (live).
Alembic upgraded to `e7f1a2c0b394` and `alembic check` reported no drift.
Generator `build_seconds` timing drift in `synthetic/vantara/expected/*/summary.json`
was reverted and not committed.

Live tests used existing local `.env` names only. Values were not printed.
An initial naive line parser left bash `$'...'` PEM quoting intact and failed
closed with `MalformedFraming`. Sourcing `.env` loaded valid keys. That was an
audit loader mistake, not a product defect.

## Railway verdict

**PASS.**

| Item | Observed |
|---|---|
| Project | `Data Pilot AI Demo` `b51aaf59-f242-4c0a-8fe0-cae999fa49b7` |
| Environment name | `production` (host environment name, not a product warehouse action) |
| Application | service `data pilot ai` `266bd07a-e32c-413d-b0be-50cc9936e806` |
| URL | `https://data-pilot-ai-production.up.railway.app` |
| Serving deployment | `430e0b75-e267-44a2-8fe2-0d03cdb9db8e` `SUCCESS`, commit `0425d32`, Dockerfile builder, healthcheck `/readyz` |
| Auto-deploy | Observable. PR 31 merged 2026-09-22T15:39:09Z; Railway created this deployment at 2026-09-22T15:39:11Z from `Fejjii/AIDataEngineer` branch `main`, reason `deploy` |
| `PORT` | `8000` (required for Railway healthchecks; image listens on 8000) |
| HTTP demo | `AIDE_SYNTHETIC_DEMO_HTTP=1`; token set; no Snowflake variables on the app |
| `GET /healthz` | 200 `{"status":"ok"}` |
| `GET /readyz` | 200 `{"status":"ok"}` |
| Authenticated demo 1 | HTTP 200, `PASS`, verifier `PASS`, determinism true, evidence 100, repair 1, humans 0, `live_smoke=NOT_RUN`. Workflow ids `d4253be0-4386-44d7-bb15-aaf5425968f0`, `f7904e70-5277-42ee-a4dd-f04712e2a91a`. HTTP 41511 ms, workflow 21542 ms, repair 6207 ms |
| Negative HTTP | 401 / 401 / 400 / 400 / 400 / 400 / 400 as required. Secret scan empty |
| Postgres | service `Postgres` `c831a852-92b1-4044-9548-c71a4ba4bd1c`, deployment `a249a7c3-b47e-41fc-b8d1-496de373335f` `SUCCESS`, image `ghcr.io/railwayapp-templates/postgres-ssl:18`, `server_version` `18.6 (Debian 18.6-1.pgdg13+2)` |
| Pre-restart persistence | 26 workflows; both demo ids present; 2 evidence bundles; 2 verifier verdicts; 2 `APPLICATION` repair events |
| Plain restart | `railway restart --service "data pilot ai" --environment production --yes --json` exit 0, returned `430e0b75-e267-44a2-8fe2-0d03cdb9db8e` |
| Post-restart | `/readyz` 200; Postgres still 18.6; both pre-restart ids and artifacts remain; 26 workflows unchanged |
| Post-restart demo | HTTP 200, same acceptance fields. Workflow ids `97591847-c08b-4927-bdbf-106708cd3738`, `33ecc8b5-ba0c-4496-aedc-0fcd98f1aa29`. HTTP 37253 ms, workflow 18891 ms, repair 5213 ms |

Shared on both live demos: scenario `interview_mvp_customer_revenue_schema_drift`,
mapping `INVOICE_STATUS → STATUS`, 10 assets, 21 models, 36 governed tool
operations, 36 policy evaluations, 23 tests, 25 quality checks, 1 incident, 690
estimated engineering minutes. Response secret findings empty.

PR 28 correctly explains the earlier failed deployments: Railway probed injected
`PORT=8080` while the image listens on 8000. Setting `PORT=8000` made later
SUCCESS deployments healthcheck-clean. Older `FAILED` records remain in history
and no longer block plain restart because they are not latest.

## Snowflake verdict

**PASS.**

| Check | Result |
|---|---|
| Snowflake RO | PASS (`test_live_ro_health_role_and_discovery`, describe/profile/sample/query, live discover VANTARA_RAW) |
| Snowflake DEV | PASS (namespace write, reject, reconcile, cleanup) |
| Least privilege | PASS. Live smoke: `ro_write_blocked`, `dev_raw_read_blocked`, `dev_raw_write_blocked`, `future_grants_inspected`, `grant_sql_executed=false` |
| RAW mutation | None. `include_schema_drift=false`. Detail states the path ran without mutating `VANTARA_RAW` |
| Staging action | None |
| Production action | `production_or_staging_action=false` |
| Identities | RO `AIDE_DEV_RO` / DEV `AIDE_DEV_RW`. Connector allow lists remain RAW+DEV for RO and `AIDE_DEV` only for DEV |

## dbt verdict

**PASS.**

Live dbt test `test_live_dbt_snowflake_debug_parse_compile_run_test_isolate_fail_cleanup`:

| Step | Result |
|---|---|
| dbt parse | PASS (`exit_code == 0`) |
| dbt compile | PASS (compiled `fct_invoices`; invoices SQL uses `AIDE_DEV` and `STATUS`, not `VANTARA_RAW`) |
| dbt run | PASS (`executed.ok`) |
| dbt tests | PASS (statuses `pass` or `warn`) |
| Isolated fail compile | PASS (intentional compile failure stays fail-closed and reconciles) |
| Cleanup | PASS (workflow schemas dropped; remaining schema query empty) |

Governed live Interview and live smoke both reported `tests_ok=true` and
`quality_ok=true`. Live smoke `raw_dev_reconciled=true`.

## Security verdict

**PASS.**

Offline: evaluation safety, least privilege, and tamper suites passed. Full
non-live suite includes import-linter vendor-execution and verifier contracts.

Railway HTTP:

| Case | Status | Detail |
|---|---:|---|
| Missing token | 401 | `demo token required` |
| Wrong token | 401 | `demo token required` (value not echoed) |
| Arbitrary SQL | 400 | `synthetic demo does not accept client input` |
| Arbitrary requirement | 400 | same |
| Malformed JSON | 400 | same |
| `target_environment=PROD` | 400 | same |
| `target_environment=STAGING` | 400 | same |

Live Snowflake write prohibition is proven from grant metadata, not DML against
`VANTARA_RAW`. No GRANT/REVOKE SQL was issued.

## Persistence verdict

**PASS.**

- Offline: 27 persistence tests passed, including restart, evidence bundle,
  verifier pack read-only assembly, and repair-budget survival.
- Railway: both pre-restart workflow ids, evidence bundles, verifier verdicts,
  and one `APPLICATION` repair event each survived application restart.
  PostgreSQL deployment id did not change. Postgres answered after restart.
- Control-plane tables present include `workflows`, `artifacts`,
  `repair_events`, twin tables, `gateway_dispatch_intents`, and audit tables.
  PostgreSQL remains the sole control-plane store.

## Determinism verdict

**PASS.**

- CLI benchmark: `Determinism: PASS` after documented identifier normalization.
- Railway demos: `determinism=true` before and after restart.
- Stable counts (assets, models, gateway operations, policy evaluations, tests,
  quality checks, incidents, repair count) matched the published sample on both
  live demos and the local benchmark.
- Offline evaluation `E-RP-01` is included in the 52 evaluation tests.

## Performance summary

Not an SLA.

| Measure | Value |
|---|---|
| Local CLI benchmark wall clock | 29323 ms MEASURED |
| Local CLI repair | 6450 ms |
| Full non-live pytest | 2345.4 s |
| Railway demo 1 HTTP / workflow / repair | 41511 / 21542 / 6207 ms |
| Railway demo 2 HTTP / workflow / repair | 37253 / 18891 / 5213 ms |
| Live Snowflake connector tests | 62.5 s |
| Live dbt test | 147.0 s |
| Governed live Interview | 293.3 s |
| Live `profile_estate` budget | 150 s, strictly below the 180 s gateway timeout |

This run did not isolate a `profile_estate`-only stopwatch. The governed live
path and live smoke PASSED, so profiling finished inside the 150 s live budget.
PR 31 on this same `main` SHA previously measured 61.65 s for the 10-table
estate. Offline tiny budget remains 60 s.

## Architecture invariants

Confirmed from source plus tests. No silent architecture change.

| Invariant | Evidence |
|---|---|
| Supervisor remains deterministic | `src/aide/app/supervisor.py` is an application phase machine. Two-run benchmark and live metrics repeat. Import-linter forbids vendor connectors in supervisor/gateway |
| Governed Tool Gateway remains execution boundary | `src/aide/app/gateway.py` is the sole connector execution path. Live smoke `gateway_connector_ids` were `snowflake_ro`, `snowflake_dev`, `dbt_dev` |
| Independent Verifier remains read-only | `aide.verification` has no gateway, connector, persistence, or repair-writer imports. `evaluate_verifier` is pure over a pack. Offline verifier PASS; tamper FAIL-closed |
| One automatic repair maximum | `MAX_APPLIED_REPAIRS_PER_TASK = 1`, `MAX_APPLIED_REPAIRS_PER_WORKFLOW = 1`. Live and CLI `apply_count=1`. `E-SF-SECOND` passed |
| No second repair class | `ACCEPTED_FROM_COLUMN=INVOICE_STATUS`, `ACCEPTED_TO_COLUMN=STATUS`, one artifact path. Broader diffs rejected in evaluation safety |
| No LLM judge for PASS or FAIL | Domain evaluation module states no LLM judge. Verifier is deterministic checks. Scorecard comes from pytest and code |
| PostgreSQL remains sole control-plane state store | Twin, workflows, artifacts, repair events, gateway intents, and audit live in PostgreSQL. No Redis/Kafka/SQLite product store |
| Snowflake identities remain least privilege | RO `READ` + `identity_class=READ_ONLY`; DEV write only `AIDE_DEV`. Live grant probe PASS |

Composition root `aide.app.interview` may import real/fake connectors. Supervisor
and gateway may not. That boundary is import-linter enforced and was exercised
by the 598-test offline suite.

## Capability truth matrix

Credit only for behavior observed in this audit or in the tests listed above.
Documentation alone is not evidence. Future V1 architecture is out of scope.

| Capability | Class | Why |
|---|---|---|
| One customer-revenue request to a verified development product | PROVEN | Offline benchmark PASS; two Railway PASS demos |
| Pinned Digital Twin and bounded estate context | PROVEN | Benchmark estate digest; twin tables on Railway; evaluation happy path |
| Deterministic Supervisor, no multi-agent framework | PROVEN | Repeatable metrics; supervisor source; vendor-import contracts |
| Governed Tool Gateway | PROVEN | 36/36 live synthetic ops; live smoke named RO/DEV/dbt connectors |
| 21 generated customer-revenue models | PROVEN | Benchmark and both Railway demos |
| Offline schema drift `INVOICE_STATUS → STATUS` | PROVEN | CLI, evaluation, Railway synthetic path |
| One allow-listed automatic repair | PROVEN | `apply_count=1`; one `APPLICATION` row per Railway demo workflow |
| Second repair / broader diff / prod-staging target rejected | PROVEN | Evaluation `E-SF-*`. HTTP body cannot carry a patch |
| Read-only Independent Verifier | PROVEN | Offline and Railway synthetic PASS. Live Snowflake path does not run it |
| Evidence completeness 100% and stored bundle | PROVEN | CLI, Railway fields, PostgreSQL artifacts before and after restart |
| Deterministic two-run benchmark | PROVEN | CLI `deterministic_repeatability: PASS`; Railway `determinism=true` |
| Human interventions stay zero | PROVEN | CLI and Railway metric 0 |
| Token-gated HTTP demo | PROVEN | 401 without or with the wrong token |
| Client SQL, requirement, and target input rejected | PROVEN | 400 |
| Health and readiness expose no secrets | PROVEN | Bodies are `{"status":"ok"}` |
| Restart persistence | PROVEN | 2/2 demo ids and bundles after app restart |
| Offline failure injection fails closed | PROVEN | 13/13 |
| Fake Snowflake and fake dbt offline path | PROVEN | Full non-live suite and Railway `live_smoke=NOT_RUN` |
| Offline v1 invoice generation still uses `INVOICE_STATUS` | PROVEN | `test_identical_inputs_produce_identical_artifacts`; PR 31 v2 live alignment did not change v1 |
| Real Snowflake RO/DEV least privilege | PROVEN | 5 live connector tests + live smoke grant metadata |
| Live dbt parse / compile / run / tests / cleanup | PROVEN | Live dbt test |
| Governed live Interview through the gateway | PROVEN | Governed pytest PASS; live smoke `governed_path_exercised=true` |
| Live `profile_estate` under 150 s | PROVEN | Path completed under the live budget and 180 s gateway timeout. Isolated 61.65 s measurement is prior evidence on this SHA, not re-stopwatched here |
| Credential-gated skip when secrets are absent | PROVEN | Category interview run deselected live tests; missing secrets do not become passes |
| PostgreSQL 16 as exclusive control-plane major version | PARTIALLY_PROVEN | Offline 16.14. Railway 18.6 works. Code does not pin major 16. PR 28 docs are unmerged |
| Terminal workflow row `COMPLETED` after verifier PASS | PARTIALLY_PROVEN | HTTP `VERIFIED`; stored state `VALIDATION` |
| Live Independent Verifier / RAW drift repair | NOT_TESTED | Accepted live contract does not mutate RAW |
| Multi-replica concurrency | NOT_TESTED | One Railway replica |
| Cryptographic tamper evidence | OUT_OF_SCOPE | Application-audit digests only |
| GitHub delivery, frontend, monitoring, second repair class, real LLM judge | OUT_OF_SCOPE | Not in Interview MVP |
| Databricks, Fabric, Airflow, BigQuery | OUT_OF_SCOPE | Future connectors only |
| Product production or staging deploy | OUT_OF_SCOPE | HTTP attempts rejected; live flag false |
| Financial ROI / token cost / warehouse credits | OUT_OF_SCOPE | Classified UNAVAILABLE, not invented |

## Repository truth

`main` `0425d32` matches the recruiter and interview story for implemented
behavior: one Vantara customer-revenue loop, pinned Twin, Supervisor, gateway,
one schema-drift repair, read-only verifier, PostgreSQL control plane, Snowflake
+ dbt, fake offline path, credential-gated live smoke.

Mismatches that remain documentation, not runtime defects:

| Claim on `main` | Observed |
|---|---|
| README / TECH_STACK / INTERVIEW_DEMO: PostgreSQL 16 | Offline 16.14. Railway 18.6. PR 28 changes the claim to 16 or newer |
| README diagram: PostgreSQL 16 node | Same |
| MVP_SCOPE: PostgreSQL 16 control state | Same. Not edited in PR 28 |
| LIVE_ACCEPTANCE_001: live Snowflake NOT_TESTED | Superseded by this audit |
| evaluation README: live least-privilege unproven | Superseded by this audit |
| Railway restart not restartable | Closed on current SUCCESS latest deployment; documented in PR 28 |

PR 28 is the correct documentation reconciliation. It does not change product
code. GitHub Actions on that PR was billing-blocked; local packaging tests on
that branch were recorded as 12 passed.

## PR 31 regression review

PR 31 (`0425d32`, live profiling efficiency) is on the audited SHA.

| Risk | Result |
|---|---|
| Offline v1 schema-drift scenario | PASS. Benchmark and evaluation still inject `INVOICE_STATUS → STATUS`. `build_interview_stack` default `fixture_version="v1"`. Generation test still asserts `INVOICE_STATUS as invoice_status` |
| Deterministic benchmark | PASS |
| Repair detection | PASS. `SCHEMA_MISMATCH`, apply count 1 |
| Evidence generation | PASS. Completeness 100% |
| Quality checks | PASS offline and live (`quality_ok=true`; quality session `USE DATABASE AIDE_DEV`) |
| Generation for invoice status | PASS. v1 keeps `INVOICE_STATUS`; live/v2 uses `STATUS` because credentialed RAW already has `STATUS` |
| Fake connectors | PASS. Offline and Railway synthetic path |
| Snowflake least privilege | PASS. Live grant metadata |

No PR 31 regression was found.

## Demo readiness

The six prepared scenarios in `docs/evaluation/DEMO_SCENARIOS_001.md` were
reviewed and reconfirmed against this SHA. Each still has a business story,
trigger, observable evidence, pass criteria, and interview explanation.

| Scenario | This audit |
|---|---|
| 1. Normal governed execution | Railway demo 1 PASS |
| 2. Schema drift repair | Same call: mapping and `apply_count=1` |
| 3. Unsafe second repair rejection | Offline `E-SF-*` PASS. HTTP cannot submit a second patch |
| 4. Evidence tamper rejection | 7/7 tamper tests PASS. Live evidence left untouched |
| 5. Unauthorized HTTP access | 401/400 matrix PASS |
| 6. Restart and persistence | Plain restart PASS; 2/2 ids remain; post-restart demo PASS |

Interview talk track remains `docs/INTERVIEW_DEMO.md`. Landing page remains
`README.md`. Say clearly: Railway is synthetic fakes; Snowflake live smoke is
the credentialed least-privilege proof and does not recreate RAW drift.

## Known limitations

- One business request and one automatic repair class.
- Live RAW is not drifted; verifier closed loop is the offline/synthetic proof.
- No GitHub delivery, UI, required live LLM provider, production, or staging.
- Evidence is application-audit immutability, not a cryptographic ledger.
- Engineering minutes are labelled ESTIMATED. Tokens, credits, and ROI are UNAVAILABLE.
- Railway environment name `production` is the host name.
- Successful rows may remain `VALIDATION` after HTTP `VERIFIED`.
- `main` docs still say PostgreSQL 16 until PR 28 merges.
- Multi-replica concurrency is untested.

## Open defects

None in product runtime or tests run for this audit.

**Documentation gap, not a product defect:** `main` still claims exclusive
PostgreSQL 16 while Railway runs 18.6. Reproduction: read README persistence
rows, then `SELECT current_setting('server_version')` on the Railway Postgres
service. Severity: Low. Remediation: merge PR 28 after review. Do not downgrade
the live database.

**Operational note:** older Railway `FAILED` deployments remain in history.
They no longer block plain restart. No product change required.

## Recommended freeze decision

**Freeze the Interview MVP.**

Do:

- Human-review and merge this audit PR (do not merge from the agent).
- Human-review and merge PR 28 so tracked docs match PostgreSQL 16 or newer
  and the Railway `PORT=8000` healthcheck fact.
- Keep `main` as the interview baseline at `0425d32` plus those documentation
  merges.

Do not:

- Add a second repair class.
- Change Snowflake grants.
- Mutate `VANTARA_RAW`.
- Enable staging or production warehouse actions.
- Redesign architecture.
- Treat the Railway environment name as product production.

The repository is recruiter-presentable as a governed control-plane demo with
an honest limitation list.
