# Operator console

**Tasks:** INTERACTIVE_VALIDATION_001 (console), UI_PRODUCT_POLISH_001 (product UI), UI_UAT_REFINEMENT_002 (interpretability)  
**Audience:** the operator who accepts the synthetic Interview scenario; interview
and recruiter demonstrations  
**Scope:** authenticated server-rendered pages inside the existing FastAPI process.

This is the fixed Vantara customer-revenue schema-drift scenario. It is not a
generic request box, an upload surface, or a validated finance product.

Related: [`SYNTHETIC_CLOUD_DEMO.md`](SYNTHETIC_CLOUD_DEMO.md),
[`INTERVIEW_DEMO.md`](../INTERVIEW_DEMO.md).

## What the console does

Sign in, inspect the selected synthetic source tables, start the existing
benchmark, and reopen the same run. One Run executes **two** workflows so the
benchmark can compare them. The page shows persisted workflow ids, generated
SQL, a bounded output preview captured from that execution, drift and repair
SQL, individual test and quality outcomes, and verifier evidence when those
artifacts exist.

## Screens

| Route | Screen | Content |
|---|---|---|
| `/console/login` | Sign-in | Data Pilot AI brand, Interview MVP and synthetic badges, operator password |
| `/console` | Overview | Summary cards (environment, scenario, data sources, models, workflow status, latest result), primary action, scenario panel with a secondary Validation scope disclosure, grouped data estate, persisted run history |
| `/console/runs/{run_id}` | Run | Persisted narrative, separated judgements, primary metrics and secondary telemetry, workflow timeline, Digital Twin estate context, incident and repaired SQL, data product preview, generated SQL, quality signals, Independent Evidence Verification, evidence bundle, audit events, exports, determinism rerun |

Presentation rules:

- The "What happened" sentence is assembled only from persisted counts and artifact fields. A missing count is omitted. The sentence does not claim a repair, an incident, or zero human interventions unless those values were stored.
- Technical workflow, evidence verification, and business correctness are separate judgements.
- Primary metrics are models, tests, quality, incident, repair, human intervention, and evidence completeness. Governed operations, policy evaluations, and determinism are secondary telemetry. Governed operations and policy evaluations count the same dispatch population.
- The timeline is business objective, estate context, model generation, execution, testing, incident, diagnosis, bounded repair, revalidation, verification, and evidence. Incident and repair stages are visually distinct. Highlighted SQL lines are the lines that differ.
- Every number on the run page is read from persisted artifacts for that run.
  The `operator_console_snapshot` artifact (schema version 2) stores the
  benchmark value metrics, evidence completeness, Digital Twin summary, and
  per-workflow phase sequence and outcomes that the run just produced. Version 1
  snapshots from earlier runs still render; the fields they lack show
  `unavailable`.
- The console reads back only allowlisted artifact types
  (`aide.persistence.console.EVIDENCE_ARTIFACT_TYPES`). All of them are already
  written by the Supervisor: repair proposal, validation and application,
  original failure, twin snapshot and estate context digests, drift observation,
  dbt parse/compile/execution/tests flags, post-repair validation, quality
  results, revenue reconciliation, gateway reconciliation, verifier verdict, and
  the evidence bundle.
- The timeline marks a stage complete only when its evidence exists. A verifier
  `FAIL`, a rejected repair, or a failed revalidation renders as an issue, never
  as a pass. While a run executes the page shows "Workflow running" and
  refreshes; no stage progress is inferred.
- Run-scoped navigation (Workflow, Incident and Repair, Data Product, Quality,
  Evidence) is shown only when a completed run exists.
- Business correctness for new runs is labelled `VALIDATED_SYNTHETIC_CONTRACT`, meaning the defined synthetic fixture contract passed the independent oracle. This is not production financial validation.
- No JavaScript. The CSP remains `script-src 'none'`; styling is one inline
  stylesheet template (`_theme.css`) and native `<details>` disclosures.

Three labels stay separate:

| Label | Meaning |
|---|---|
| Run status | `running`, `completed`, or `failed` |
| Evidence consistency | Independent Verifier `PASS` or `FAIL` only when that artifact was stored. Otherwise `unavailable` |
| Business correctness | `VALIDATED_SYNTHETIC_CONTRACT` for the defined synthetic fixture contract on current builds; not a production finance certification |

A verifier PASS is evidence consistency for the schema-drift repair. It is not production financial validation. The independent fixture oracle separately validates the defined synthetic contract for currency isolation, refunds, net paid amount, grain, duplicate payments, deleted CRM handling, and unknown customer handling. FX conversion and several broader finance measures remain out of scope.

Refreshing a result page does not start another run. A second Run while one is
active returns HTTP 409. If the process restarts mid-run, the row is marked
failed and completion evidence stays unavailable.

## Operator authentication

Set `AIDE_OPERATOR_PASSWORD` to a value of at least 12 characters. A missing or
shorter value refuses sign-in. The password is compared as a digest. It is not
written to the URL, the session cookie, logs, or the HTML.

The session cookie `aide_session` is HttpOnly and SameSite=Lax. Set
`AIDE_SESSION_COOKIE_SECURE=1` when the browser uses HTTPS. Mutations require
the server-rendered CSRF field. The console issues the OPERATOR role only.

Anonymous legacy routes are off unless `AIDE_LEGACY_ANONYMOUS_ROUTES=1`:

| Method | Path |
|---|---|
| `POST` | `/v1/sessions` |
| `POST` | `/v1/workflows` |
| `GET` | `/v1/workflows/{workflow_id}/events` |

Leave that flag unset on the deployed demo. Local tests that still exercise
those routes opt in explicitly.

`POST /v1/interview/demo` stays token-gated and unchanged. The console and that
route share one runner. A busy runner rejects the other caller.

## Local synthetic run

PostgreSQL must already be migrated (`alembic upgrade head`, including
`b7e4c1a09d55`). From the repository root:

```bash
# Export AIDE_OPERATOR_PASSWORD (12 or more characters) and AIDE_CSRF_SECRET
# (32 or more characters) in this shell before starting the process.
export AIDE_SESSION_COOKIE_SECURE=0
export AIDE_LEGACY_ANONYMOUS_ROUTES=0
uv run uvicorn asgi:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/console/login`. Do not put the password in the
command history of a shared shell if that history is retained.

Exports are allowlisted names under
`/console/runs/{run_id}/exports/{name}`: `output-preview`, `original-sql`,
`repaired-sql`, `generated-sql`, `quality`, `verifier`, `tests`. Anything else
is `unavailable`.

## Railway deployment and retained configuration checklist

Verified 2026-09-30: the console and current synthetic validation wording are
serving from main `a9e65ce7597354fba58bf190dd40042d707703ec`, deployment
`a29fe27b-9858-4526-a8e8-d5654e687246` (SUCCESS). Health and readiness passed.
This records existing deployment state; it does not authorize redeployment.
The following configuration checklist remains applicable:

1. Deploy the application image that contains this revision. The container
   entrypoint already runs Alembic before the process serves traffic.
2. Set `AIDE_OPERATOR_PASSWORD` (12 characters or more) on the service.
3. Set `AIDE_SESSION_COOKIE_SECURE=1`.
4. Leave `AIDE_LEGACY_ANONYMOUS_ROUTES` unset or `0`.
5. Keep the existing database URL, CSRF secret, and demo-token settings. Do not
   print them.
6. Open `/console/login` on the existing public domain. Confirm
   `POST /v1/sessions` returns 404 before sharing the URL.

## Acceptance checklist

- [ ] Sign-in is required for the console, Run, history, evidence, and exports.
- [ ] A rejected sign-in or missing CSRF writes no session and no run.
- [ ] Legacy anonymous session, workflow, and event routes are absent unless
      `AIDE_LEGACY_ANONYMOUS_ROUTES=1`.
- [ ] The page shows the fixed scenario, objective, synthetic label, selected
      tables, schema, and masked sample rows. There is no request box or upload.
- [ ] Run starts the real two-workflow benchmark. Refresh does not start another.
- [ ] A second Run while one is active is rejected.
- [ ] History comes from PostgreSQL artifacts, not a process temporary file.
- [ ] Missing artifacts say unavailable. They are not labelled PASS.
- [ ] Execution, evidence consistency, and business correctness stay distinct.
- [ ] Currency, refund, and history limitations are visible.
- [ ] HTML in a failure message is escaped. Export paths stay on the allowlist.
- [ ] The engineering-loop timeline, result summary, incident and repair, quality,
      verification, and evidence panels show persisted values or `unavailable`.
- [ ] The page is usable at about 1440 px, tablet width, and about 390 px.

## Human acceptance script

**Status: USER_ACCEPTANCE_NOT_RUN.** Automated checks do not replace this script. The synthetic business contract has passed the independent fixture oracle, but operator acceptance is still pending.
Sofien completes it on the deployed or local synthetic process.

1. Sign in at `/console/login`.
2. Inspect the scenario, objective, synthetic label, Validation scope, and the
   grouped masked source samples.
3. Start a run. Confirm the page says "Workflow running" and does not invent
   stages while the benchmark executes two workflows.
4. When the run completes, read What happened, the separated judgements, and the
   timeline. Confirm every value comes from this run (compare with the exports)
   and that nothing shows a PASS where evidence is missing.
5. Inspect the incident and repair panel: failure class, `INVOICE_STATUS` to
   `STATUS`, original SQL, repaired SQL, repair validation rules, and
   revalidation.
6. Inspect generated SQL and the actual output preview. Confirm the page states that the defined synthetic contract is validated while production financial validation remains out of scope.
7. Examine dbt tests, quality checks, reconciliation, and the Independent
   Evidence Verification panel separately. Note anything marked unavailable.
8. Reopen the same run from history. Confirm the workflow ids did not change
   and no second run started.
9. Repeat steps 1, 4, and 5 in a narrow (about 390 px) browser window.

Record the run id and what you accepted or rejected. Do not treat scoped synthetic contract validation as production financial certification.

## Synthetic business correctness contract

The current build has an independent fixture-derived oracle in `aide.quality.business_oracle`.
It validates the generated mart against committed v1 and v2 source fixtures without
reusing the mart SQL as its expected answer.

The accepted synthetic contract covers:

* canonical EUR, USD, and GBP currency isolation with no FX conversion
* one row per customer, day, and currency
* invoice totals from invoice lines on invoice issue date
* deduplicated payment totals on payment date
* refund totals on refund date
* net paid amount equal to paid amount minus refunded amount
* deterministic duplicate payment handling
* exclusion of deleted CRM accounts from survivorship
* preservation of the unknown customer member

The independent oracle and generated mart match for the committed fixtures. This
supports the status `VALIDATED_SYNTHETIC_CONTRACT`.

Remaining scope limits are explicit:

* no FX conversion or base-currency reporting
* no open invoice amount
* no active subscription metric
* no MRR calculation
* customer and plan history remain simplified current-row shapes
* this validation does not certify arbitrary customer data or production finance

See `docs/evaluation/BUSINESS_CORRECTNESS_001.md` for the exact expectations,
before-state defects, fixture totals, and regression evidence.
