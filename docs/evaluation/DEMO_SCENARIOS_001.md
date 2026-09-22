# Interview demo scenarios — LIVE_ACCEPTANCE_001

Six scenarios for a recruiter or hiring-manager conversation about the deployed
Data Pilot AI Interview MVP. Each scenario is one business story with a
deterministic pass rule. No LLM judge.

Deployment observed on 2026-09-22:

- Railway project `Data Pilot AI Demo`
- Railway environment name `production` (this is the host environment name, not a product staging or production warehouse action)
- Application service `data pilot ai`
- Public URL `https://data-pilot-ai-production.up.railway.app`
- Serving deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d` from `main` `b3a4291`
- PostgreSQL service left running; application process restarted in place

The HTTP demo runs only `interview_mvp_customer_revenue_schema_drift` through
the offline benchmark. One authenticated `POST /v1/interview/demo` executes
that scenario twice so determinism can be compared. The response reports one
repair for the scored run. Do not send SQL, a requirement, or a target
environment. Those bodies are rejected.

## 1. Normal governed execution

**Business story.** Vantara asks for a customer-revenue data product. Data Pilot
AI pins the estate, generates the bounded dbt product, validates it, and
returns a verifier verdict. A human does not approve the repair.

**Setup.** HTTP demo enabled with `AIDE_SYNTHETIC_DEMO_HTTP=1` and a nonempty
`AIDE_SYNTHETIC_DEMO_TOKEN`. PostgreSQL reachable from the app. No Snowflake
credentials on this path.

**Trigger.**

```bash
curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -H "X-AIDE-Demo-Token: ${AIDE_SYNTHETIC_DEMO_TOKEN}" \
  -d '{}' \
  https://data-pilot-ai-production.up.railway.app/v1/interview/demo
```

**Expected behavior.** HTTP 200. `workflow_status=VERIFIED`. Two new workflow
ids. `live_smoke=NOT_RUN`. Benchmark counts match the published offline sample:
10 assets, 21 models, 36 governed tool operations, 36 policy evaluations, 23
tests, 25 quality checks, 1 incident, 0 human interventions.

**Observable evidence.** Five sequential calls on 2026-09-22 each returned HTTP
200, `benchmark_verdict=PASS`, and `secret_findings` empty. Workflow duration
was 19.4–21.9s. HTTP elapsed time was 39.9–44.4s because each call runs the
scenario twice.

**Pass criteria.** `benchmark_verdict=PASS`, `human_interventions=0`,
`live_smoke=NOT_RUN`, and the response contains no credential material.

**Interview explanation.** The control plane accepted one fixed business
request and executed it through the Supervisor and Governed Tool Gateway.
Snowflake and dbt on this URL are the deterministic fakes. The Independent
Verifier, not an LLM, produced PASS.

## 2. Schema drift repair

**Business story.** Billing renamed `INVOICE_STATUS` to `STATUS`. The pipeline
must detect that drift, apply the one allow-listed column-reference repair,
and revalidate. It must not invent a broader SQL change.

**Setup.** Same authenticated empty JSON body as scenario 1. The drift is
injected inside the accepted scenario. The client does not supply the mapping.

**Trigger.** The same `POST /v1/interview/demo` with `{}`.

**Expected behavior.** `schema_drift.detected=true`,
`failure_class=SCHEMA_MISMATCH`, mapping `INVOICE_STATUS → STATUS`,
`repair.applied=true`, `repair.allowed=true`, `repair.apply_count=1`.

**Observable evidence.** All five acceptance runs and the post-restart run
reported that mapping and `apply_count=1`. PostgreSQL `repair_events` for the
ten workflow ids from the five runs contained exactly one `APPLICATION` event
per workflow, plus one each of `PROPOSAL`, `VALIDATION`, `REVALIDATION`, and
`VERDICT`.

**Pass criteria.** Drift detected, exactly one application per workflow, and
the verifier still PASS.

**Interview explanation.** Diagnosis is a typed schema mismatch, not a retry
loop. The repair validator allows one column reference on the accepted
invoice staging model. A second application is a different scenario.

## 3. Unsafe second repair rejection

**Business story.** After the allow-listed repair has already been applied,
another automatic patch is proposed. The control plane must refuse it, including
a recursive repair, a broader SQL diff, a wrong table, or a weakened test.

**Setup.** Offline evaluation. The deployed HTTP route has no client field for
a second repair. Do not try to pass a patch in the JSON body; scenario 5 shows
that the body is rejected before any workflow starts.

**Trigger.** `tests/evaluation/test_safety.py::test_second_repair_is_rejected`
and the related `E-SF-*` cases (`SECOND`, `RECUR`, `BROADER`, `TABLE`, `COL`,
`TYPE`, `TEST`, `PERM`, `PROD`).

**Expected behavior.** `validate_repair` returns `allowed=false` with
`SECOND_REPAIR` when `applied_count` is already 1. Production and staging
targets are denied. The workflow is not given a second automatic application.

**Observable evidence.** This acceptance run did not send a second patch to
Railway. The live runs showed `apply_count=1` and one `APPLICATION` row per
workflow, which is the budget the rejection rule enforces. The offline
`E-SF-SECOND` test is the direct rejection proof. Record its pytest result
from `docs/evaluation/LIVE_ACCEPTANCE_001.md`.

**Pass criteria.** Second repair is not allowed. Live repair count stays 1.
No production or staging target is executed.

**Interview explanation.** The platform ceiling in the architecture is wider.
The Interview MVP applies at most one automatic repair, and only the
allow-listed `INVOICE_STATUS` to `STATUS` reference. Anything else fails closed.

## 4. Evidence tamper rejection

**Business story.** Someone changes an evidence digest, rebinds a bundle to
the wrong workflow or snapshot, or mixes execution modes after the fact. The
Independent Verifier must FAIL. It must not rewrite the workflow to make the
bundle look valid.

**Setup.** Offline tamper tests against persisted artifacts. The HTTP demo
does not expose an evidence-edit API.

**Trigger.** `tests/evaluation/test_tamper.py`: section digest, bundle digest,
workflow binding, snapshot binding, rehashed execution mode, drift identity,
and artifact hash.

**Expected behavior.** Completeness or the verifier fails. A rehashed mixed
`execution_mode` bundle does not count as complete.

**Observable evidence.** Live runs stored one `evidence_bundle` and one
`verifier_verdict` artifact per workflow. A sampled verdict body was `PASS`
with checks present. Tamper rejection itself is the offline suite, not a live
mutation of Railway rows. This task did not modify stored evidence.

**Pass criteria.** Untampered live evidence stays queryable and the verifier
artifact says `PASS`. Tamper fixtures fail closed in `tests/evaluation/test_tamper.py`.

**Interview explanation.** Evidence is an application-audit manifest of
digests. The verifier is read-only. This is not cryptographic tamper-evidence
storage. A changed digest fails the verdict; the product does not claim a
ledger that cannot be edited by a database administrator.

## 5. Unauthorized HTTP access

**Business story.** The public URL is reachable. A caller without the demo
token, or with the wrong token, must not start a workflow. A caller who sends
SQL or a production target must not be treated as a warehouse client.

**Setup.** HTTP demo enabled. Do not print the token.

**Trigger.**

| Call | Body | Token |
|---|---|---|
| Missing token | `{}` | absent |
| Wrong token | `{}` | any other value |
| Arbitrary SQL | `{"sql":"DROP TABLE workflows"}` | valid |
| Arbitrary requirement | `{"requirement":"deploy this to production"}` | valid |
| Malformed JSON | `{not-json` | valid |
| Production target | `{"target_environment":"PROD"}` | valid |
| Staging target | `{"target_environment":"STAGING"}` | valid |

**Expected behavior.** Missing and wrong token: HTTP 401, detail
`demo token required`, token value not echoed. Every non-empty or malformed
body: HTTP 400, detail `synthetic demo does not accept client input`. Health
and readiness stay `{"status":"ok"}`.

**Observable evidence.** On 2026-09-22 the seven negative calls returned
401, 401, 400, 400, 400, 400, and 400. Secret scan of those bodies was empty.
`GET /healthz` and `GET /readyz` returned 200 with only `status`. Railway HTTP
logs for the window contained 2×401, 5×400, 6×200, and 1×409 on
`POST /v1/interview/demo`, and the token string was not present in the fetched
runtime or HTTP logs.

**Pass criteria.** 401 for bad auth, 400 for client input, no workflow created
by those calls, no credential in the response or the sampled logs.

**Interview explanation.** The route is an env-gated switch for one synthetic
scenario. It is not a SQL API. Railway's environment happens to be named
`production`; that name does not grant `PRODUCTION_WRITE` or `STAGING_DEPLOY`.
Successful demo payloads report `live_smoke=NOT_RUN`.

## 6. Restart and persistence

**Business story.** The application process restarts during a demo day.
Control-plane state must still be in PostgreSQL. The next demo must pass
again. Restarting the app must not be a product deploy to a customer warehouse.

**Setup.** Capture workflow ids from successful HTTP demos. Leave the Postgres
service running. Restart the serving application deployment, not Postgres.

**Trigger.** Restart deployment `a2a4d72e-62d3-420f-bb71-850d1ef8007d`.
`railway restart` against the latest deployment returned
`Deployment is not restartable` because a later deployment of the same commit
is `FAILED` and is not the serving one. The serving deployment was restarted
directly. Logs showed shutdown at 2026-09-22T07:42:23Z and startup complete at
2026-09-22T07:42:25Z.

**Expected behavior.** `/readyz` returns 200. PostgreSQL answers `SELECT 1`.
Previous workflow rows and `evidence_bundle` artifacts remain. A new
authenticated demo returns PASS.

**Observable evidence.** After restart, 12 of 12 pre-restart workflow ids were
still present, each with an evidence bundle. A sampled `verifier_verdict` was
still `PASS`. Postgres stayed deployment `a249a7c3-b47e-41fc-b8d1-496de373335f`
on PostgreSQL 18.6. The next HTTP demo was HTTP 200, `VERIFIED`, verifier
`PASS`, determinism true, repair count 1, human interventions 0, evidence
completeness 100. New workflow ids were `873e215a-b708-42ab-b7c6-9338fd5e4f47`
and `721421c7-8d2b-455f-b218-dfb65e3fd717`.

**Pass criteria.** No loss of prior workflow or evidence rows. Postgres stays
up. One post-restart demo passes with the same acceptance fields as scenario 1.

**Interview explanation.** PostgreSQL is the control plane. The app container
is replaceable. Evidence from earlier demos is still queryable after the
process starts again. This restart did not run Snowflake, staging, or
production actions.

## Concurrency note for scenario 1

Two authenticated empty-body requests started 2ms apart. One returned HTTP 409
in 661ms with no workflow ids. The other returned HTTP 200 with exactly two
new workflow ids and `PASS`. The workflow table grew by 2, from 14 to 16, not
by 4. The in-process lock allows one synthetic demo at a time on this single
replica. It was not tested across multiple replicas.
