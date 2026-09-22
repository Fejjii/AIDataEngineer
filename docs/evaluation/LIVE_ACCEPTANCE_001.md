# Live acceptance — LIVE_ACCEPTANCE_001

**Verdict:** `ACCEPTED_WITH_LIMITATIONS`

**Date:** 2026-09-22  
**Repository:** Fejjii/AIDataEngineer  
**Base:** `main` `b3a4291d44ee8eab32d1cc377551246e7e65c5c5`  
**Host:** Railway project `Data Pilot AI Demo`, environment name `production`  
**Application:** service `data pilot ai`, URL `https://data-pilot-ai-production.up.railway.app`  
**Serving deployment:** `a2a4d72e-62d3-420f-bb71-850d1ef8007d` (`SUCCESS`, commit `b3a4291`, Dockerfile builder)  
**PostgreSQL service:** `Postgres`, deployment `a249a7c3-b47e-41fc-b8d1-496de373335f` (`SUCCESS`, image `ghcr.io/railwayapp-templates/postgres-ssl:18`)  
**Observed database:** PostgreSQL 18.6  
**Product code changes:** none

The Railway environment is named `production`. That name is the host environment. It is not a product staging or production warehouse action. Every successful demo in this run reported `live_smoke=NOT_RUN`.

Demo scenarios for an interview conversation: [`DEMO_SCENARIOS_001.md`](DEMO_SCENARIOS_001.md).

## Overall verdict

`ACCEPTED_WITH_LIMITATIONS`

The serving application performed the accepted Interview MVP loop five times, rejected unauthorized and malformed HTTP input, kept a single in-process demo lock, and kept workflow and evidence rows across an application restart. The offline suites for evaluation, interview integration, tamper, failure injection, persistence, and the CLI benchmark passed. Eight live Snowflake and live dbt tests were skipped because credentials were not present.

Limitations that block a bare `ACCEPTED`: live Snowflake least-privilege was not exercised; the deployed database is PostgreSQL 18.6 while the product documents PostgreSQL 16; a later deployment of the same commit is `FAILED` and is not serving, so `railway restart` without a deployment id returns `Deployment is not restartable`.

## Offline test result

Local PostgreSQL 16.14 in an ephemeral container. Full suite database `127.0.0.1:5433`. Category suites and the CLI benchmark used `127.0.0.1:5434`. No Snowflake credentials were set.

| Suite | Command | Result |
|---|---|---|
| Full offline regression | `uv run pytest -q --tb=line` | **588 passed, 8 skipped, 1 failed**, 0 errors, 597 tests, 2373.1s, exit 1 |
| Evaluation | `uv run pytest tests/evaluation -q --tb=line` | **52 passed, 0 failed, 0 skipped**, exit 0 |
| Interview integration | `uv run pytest tests/integration/interview -q --tb=line` | **25 passed, 0 failed, 1 skipped**, exit 0 |
| Security | `uv run pytest tests/security -q --tb=line` | **6 passed, 0 failed, 0 skipped**, exit 0 |
| Tamper | `uv run pytest tests/evaluation/test_tamper.py -q --tb=line` | **7 passed, 0 failed, 0 skipped**, exit 0 |
| Failure injection | `uv run pytest tests/evaluation/test_failure_injection.py -q --tb=line` | **13 passed, 0 failed, 0 skipped**, exit 0 |
| Persistence | evaluation persistence plus interview restart, evidence, verifier, and repair-budget tests | **27 passed, 0 failed, 0 skipped**, exit 0 |
| Deterministic benchmark | `uv run aide interview benchmark` | **PASS**, exit 0 |

The full-suite failure is `tests/security/test_leakage.py::test_leakage_scan_detects_no_secrets`. The only hit was a gitignored local helper under `.ai/local/` that contained a quoted dummy token assignment longer than the scanner's fixture allowance. It is not product code and was not committed. The helper was shortened. The later `tests/security` run, which includes that same test, passed 6/6.

The eight skips are credential-gated live tests:

- `test_live_dbt_snowflake_debug_parse_compile_run_test_isolate_fail_cleanup`
- `test_at18_at19_at24_live_interview_smoke`
- `test_real_live_discover_vantara_raw`
- `test_live_ro_health_role_and_discovery`
- `test_live_ro_describe_profile_sample_relationships_and_query`
- `test_live_deadline_timeout`
- `test_live_dev_namespace_write_reject_reconcile_and_cleanup`
- `test_at24_governed_live_interview_uses_tool_gateway`

The interview-integration skip is the last of those.

CLI benchmark on local PostgreSQL 16: Independent Verifier `PASS`, determinism `PASS`, evidence completeness 100%, repair applied once, human interventions 0, wall clock 30377 ms measured, repair 6313 ms, `model_tokens` / `model_cost_usd` / `warehouse_credits` `UNAVAILABLE`, estimated engineering time 690 minutes labelled `ESTIMATED`.

## Live run success rate

**5 of 5 acceptance runs PASS.** One additional post-restart run also PASS. It is not part of the five-run rate.

Each call is `POST /v1/interview/demo` with body `{}` and header `X-AIDE-Demo-Token`. One call runs the scenario twice. `repair_count` below is the reported `repair.apply_count` for the scored run. Database checks showed one `APPLICATION` repair event per workflow id.

| Run | HTTP | Workflow ids | Status | Drift | Repair | Verifier | Evidence | Determinism | Benchmark | Humans | Workflow ms | Repair ms | HTTP ms |
|---|---:|---|---|---|---:|---|---:|---|---|---:|---:|---:|---:|
| 1 | 200 | `cc930632-1717-44a0-9e89-1b5ca5fe45b5`, `187cc5df-12fe-4056-82d4-e6e1ff9cd5bc` | VERIFIED | true `SCHEMA_MISMATCH` | 1 | PASS | 100 | true | PASS | 0 | 20068 | 5642 | 40410 |
| 2 | 200 | `d22fce1a-6337-46c2-85b9-fdb2d9e61da0`, `c52c0b98-faf4-4fda-9d7e-096d2cde3712` | VERIFIED | true `SCHEMA_MISMATCH` | 1 | PASS | 100 | true | PASS | 0 | 19671 | 5584 | 39889 |
| 3 | 200 | `fd7d6ab6-8b62-4f49-a4a0-14000e4981ee`, `db0f0586-42f7-4871-afdc-30f6f6c88b90` | VERIFIED | true `SCHEMA_MISMATCH` | 1 | PASS | 100 | true | PASS | 0 | 21866 | 7896 | 44428 |
| 4 | 200 | `edb0c0b2-3b06-4596-9614-5a51ac6dfcc1`, `2b7ca846-493f-4656-b544-25e36f8f5eb0` | VERIFIED | true `SCHEMA_MISMATCH` | 1 | PASS | 100 | true | PASS | 0 | 19449 | 5631 | 40922 |
| 5 | 200 | `74d6917e-157b-4b9a-b212-5e3e73655c93`, `07ec6124-bb01-414c-b410-ced3bd2debbf` | VERIFIED | true `SCHEMA_MISMATCH` | 1 | PASS | 100 | true | PASS | 0 | 21306 | 6452 | 41676 |

Shared on all five: scenario `interview_mvp_customer_revenue_schema_drift`, mapping `INVOICE_STATUS → STATUS`, repair applied and allowed, `live_smoke=NOT_RUN`, 10 assets, 21 models, 36 governed tool operations, 36 policy evaluations, 23 tests, 25 quality checks, 1 incident, 690 estimated engineering minutes. Secret scan of each response body was empty.

Post-restart run: HTTP 200, `873e215a-b708-42ab-b7c6-9338fd5e4f47` and `721421c7-8d2b-455f-b218-dfb65e3fd717`, same pass fields, workflow 19628 ms, repair 5123 ms, HTTP 38556 ms.

## Security negative test result

**PASS** on the serving URL.

| Case | Status | Body |
|---|---:|---|
| Missing token | 401 | `demo token required` |
| Wrong token | 401 | `demo token required` (token not echoed) |
| Arbitrary SQL object | 400 | `synthetic demo does not accept client input` |
| Arbitrary requirement | 400 | `synthetic demo does not accept client input` |
| Malformed JSON | 400 | `synthetic demo does not accept client input` |
| `target_environment=PROD` | 400 | `synthetic demo does not accept client input` |
| `target_environment=STAGING` | 400 | `synthetic demo does not accept client input` |
| `GET /healthz` | 200 | `{"status":"ok"}` |
| `GET /readyz` | 200 | `{"status":"ok"}` |

Response bodies from these calls had no configured-secret hits and no connection-string userinfo. Health and readiness bodies are only `status`. A bounded fetch of application runtime logs and HTTP logs contained no configured token, CSRF secret, or database URL. HTTP log counts in that window: `POST /v1/interview/demo` 200×6, 400×5, 401×2, 409×1; `GET /healthz` 200×2; `GET /readyz` 200×2.

`AIDE_SYNTHETIC_DEMO_HTTP` is enabled. The token and CSRF secret are set and were not printed. No Snowflake variable is configured on the app service.

## Persistence result

**PASS.**

Before the five runs the database had 4 workflows, all `VALIDATION`, with evidence bundles. After five runs it had 14. After the concurrency pair it had 16. All 10 acceptance workflow ids were present, each with an `evidence_bundle` artifact and a `verifier_verdict` artifact. A sampled verdict body was `PASS`. Repair-event kinds across those 10 workflows were 10 `APPLICATION`, 10 `PROPOSAL`, 10 `VALIDATION`, 10 `REVALIDATION`, and 10 `VERDICT` (one application per workflow).

`railway restart` on the latest deployment failed with `Deployment is not restartable` because latest deployment `63ca238c-996f-4702-9f4e-fed91f64325c` is `FAILED`. The serving deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d` was restarted directly. Logs show process shutdown at 2026-09-22T07:42:23Z and startup complete at 2026-09-22T07:42:25Z. `/readyz` returned 200. Postgres deployment id did not change. `SELECT 1` succeeded. After restart, 12 of 12 pre-restart workflow ids were still present, each with an evidence bundle. The next authenticated demo passed.

Persisted workflow `state` for these successful runs remained `VALIDATION`. The HTTP status is `VERIFIED`. Existing interview tests allow `VALIDATION` or `COMPLETED` after success. This is observed behavior, not a new failure.

## Determinism result

**PASS.** `determinism=true` on all five acceptance runs and on the post-restart run. Local `aide interview benchmark` printed `Determinism: PASS`. Stable counts (assets, models, gateway operations, policy evaluations, tests, quality checks, incidents, repair count) did not vary across the five live runs. Workflow ids and durations varied, which is the documented normalization case.

## Verifier result

**PASS.** `verifier_verdict=PASS` on all five acceptance runs, the concurrency winner, and the post-restart run. A stored `verifier_verdict` artifact for the first acceptance workflow also read `PASS`.

## Performance summary

Not an SLA. Railway HTTP time includes two internal scenario runs.

| Measure | Five live runs |
|---|---|
| Reported workflow duration | min 19449 ms, max 21866 ms, mean 20472 ms |
| Reported repair duration | min 5584 ms, max 7896 ms, mean 6241 ms |
| HTTP elapsed | min 39889 ms, max 44428 ms, mean 41465 ms |
| Local CLI benchmark wall clock | 30377 ms measured |
| Local CLI repair duration | 6313 ms |
| Full offline pytest | 2373.1 s |

Concurrency pair, started 2 ms apart: HTTP 409 in 661 ms with no workflow ids, and HTTP 200 in 43190 ms with exactly two workflow ids and `PASS`. Workflow count increased by 2 (14 to 16), so the rejected call did not create a second pair.

## Capability truth matrix

Credit is only for behavior observed in this run or in the offline tests above. Documentation alone is not evidence. Future architecture is out of scope.

| Capability | Class | Why |
|---|---|---|
| One customer-revenue request to a verified development product | PROVEN | Five live PASS runs and local benchmark PASS |
| Pinned Digital Twin and bounded estate context | PROVEN | Live scenario metrics; stored `twin_snapshot` artifacts; verifier body includes `twin_snapshot_id` |
| Deterministic Supervisor, no multi-agent framework | PROVEN | Repeatable live metrics; import-boundary tests passed in the full suite |
| Governed Tool Gateway on the synthetic path | PROVEN | Live `governed_tool_operations=36` and `policy_evaluations=36` on every run |
| 21 generated customer-revenue models | PROVEN | Live and CLI benchmark |
| Schema drift `INVOICE_STATUS → STATUS` | PROVEN | Live field on every run |
| One allow-listed automatic repair | PROVEN | `apply_count=1`; one `APPLICATION` event per workflow |
| Second repair, broader diff, and production/staging repair targets rejected | PROVEN | `tests/evaluation` safety cases passed. Not sent as a live patch; the HTTP body cannot carry one |
| Read-only Independent Verifier | PROVEN | Live PASS; tamper tests passed; verifier source has no mutation API |
| Evidence completeness 100% and stored bundle | PROVEN | Live field and PostgreSQL artifacts before and after restart |
| Deterministic two-run benchmark | PROVEN | Live `determinism=true`; CLI scorecard `deterministic_repeatability: PASS` |
| Human interventions stay zero | PROVEN | Live metric 0 |
| Token-gated HTTP demo | PROVEN | 401 without or with the wrong token |
| Client SQL, requirement, and target input rejected | PROVEN | 400, no workflow from those calls |
| Health and readiness expose no secrets | PROVEN | Bodies are `{"status":"ok"}` |
| Single-replica concurrency guard | PROVEN | 409 plus one 200; workflow table grew by one pair |
| Restart persistence of workflows and evidence | PROVEN | 12/12 ids and bundles after app restart; Postgres stayed up |
| Offline failure injection fails closed | PROVEN | 13/13 evaluation failure-injection tests |
| Credential-gated skip when Snowflake secrets are absent | PROVEN | 8 live tests skipped; missing credentials did not weaken them into passes |
| Real Snowflake RO/DEV least privilege and live dbt | NOT_TESTED | Those 8 tests skipped; Railway demo reports `live_smoke=NOT_RUN` |
| PostgreSQL 16 as the only control-plane major version | PARTIALLY_PROVEN | Offline suites used 16.14. The deployed service is PostgreSQL 18.6 and the live loop passed on it |
| Terminal workflow row `COMPLETED` after verifier PASS | PARTIALLY_PROVEN | HTTP status is `VERIFIED`. Stored `workflows.state` stayed `VALIDATION`, which current tests allow |
| Cryptographic tamper evidence | OUT_OF_SCOPE | Docs and verifier behavior are application-audit digests. Tamper tests prove digest failure, not an immutable ledger |
| GitHub delivery, frontend, monitoring, second repair class, real LLM judge | OUT_OF_SCOPE | Not in the Interview MVP. Not inferred from V1 design docs |
| V1 scenarios S03–S11, `aide eval`, duplicate-payment repair | OUT_OF_SCOPE | Evaluation strategy marks them as design, not this demo |
| Product production or staging deploy | OUT_OF_SCOPE | HTTP attempts were rejected. No such action was observed |
| Multi-replica concurrency | NOT_TESTED | One Railway replica. The lock is in-process |

## Defects found

No product runtime defect was found. No product code was changed.

**Operational finding — later deployment is FAILED and blocks `railway restart`.**

| Field | Value |
|---|---|
| Severity | Medium for operators. The serving deployment still passed the live gates |
| Reproduction | `railway deployment list --service "data pilot ai"`. Latest id `63ca238c-996f-4702-9f4e-fed91f64325c` is `FAILED` (created 2026-09-22T07:20:53Z, same commit `b3a4291`). `railway restart --service "data pilot ai" --yes` returns `Deployment is not restartable` |
| Expected | Restart the process that is serving traffic without a manual deployment id |
| Actual | The serving `SUCCESS` deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d` kept running. Its logs show an earlier container start, then a stop of the failed deployment's container. No secret-bearing error line was present. The failure cause beyond that log is UNKNOWN |
| Affected capability | Operator restart of the app service. Not the Interview MVP loop on the serving revision |
| Remediation | An operator should inspect that failed deployment and remove or replace it so the latest deployment is the one that serves. Do not change Interview MVP code for this |

The full-suite leakage failure is recorded under offline results. It is not a product defect.

## Limitations

- Live Snowflake and live dbt were not run.
- Deployed PostgreSQL is 18.6, not the documented 16.
- This URL runs fake Snowflake and fake dbt. `live_smoke=NOT_RUN`.
- Successful rows remain in `VALIDATION` while the demo status is `VERIFIED`.
- Concurrency was proven for one replica only.
- Evidence is application-audit immutability.
- Engineering minutes are labelled estimates. Token cost, warehouse credits, and ROI were not invented.
- Uvicorn `INFO` lines are stored with Railway level `error`. No secret was in those lines. This does not change the verdict.
- A failed deployment remains the latest deployment record.

## Recommended next step

Human review of the evaluation PR. Do not merge from the agent. Do not treat this host as production-ready. After review, an operator can clear the failed Railway deployment so a plain `railway restart` targets the serving revision. The next product proof, if wanted, is a credential-gated Snowflake live smoke on a host that already has the named secrets. That work is outside this acceptance task.
