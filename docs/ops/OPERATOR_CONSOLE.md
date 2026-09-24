# Operator console

**Tasks:** INTERACTIVE_VALIDATION_001 (console), UI_PRODUCT_POLISH_001 (product UI)  
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
| `/console/runs/{run_id}` | Run | Result summary, engineering-loop timeline, Digital Twin estate context, incident and bounded repair before/after, data product preview and generated SQL, separated quality signals, Independent Evidence Verification, evidence bundle, audit events, exports, determinism rerun |

Presentation rules:

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
- Business correctness stays `NOT_VALIDATED` on the overview, the run header,
  the data product panel, the verification panel, and every history row.
- No JavaScript. The CSP remains `script-src 'none'`; styling is one inline
  stylesheet template (`_theme.css`) and native `<details>` disclosures.

Three labels stay separate:

| Label | Meaning |
|---|---|
| Run status | `running`, `completed`, or `failed` |
| Evidence consistency | Independent Verifier `PASS` or `FAIL` only when that artifact was stored. Otherwise `unavailable` |
| Business correctness | Always `NOT_VALIDATED` |

A verifier PASS is evidence consistency for the schema-drift repair. It is not
validated financial revenue. Mixed-currency gross sums, un-netted refunds, and
history-shape columns stay visible as limitations. This task does not invent FX
rates or change the generated SQL.

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

## Railway (prepare only)

Do not change the live service from this task. When Development Control deploys
this image later:

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

**Status: USER_ACCEPTANCE_NOT_RUN.** Automated checks do not replace this script.
Sofien completes it on the deployed or local synthetic process.

1. Sign in at `/console/login`.
2. Inspect the scenario, objective, synthetic label, Validation scope, and the
   grouped masked source samples.
3. Start a run. Confirm the page says "Workflow running" and does not invent
   stages while the benchmark executes two workflows.
4. When the run completes, read the result summary and the engineering-loop
   timeline. Confirm every value comes from this run (compare with the exports)
   and that nothing shows a PASS where evidence is missing.
5. Inspect the incident and repair panel: failure class, `INVOICE_STATUS` to
   `STATUS`, original SQL, repaired SQL, repair validation rules, and
   revalidation.
6. Inspect generated SQL and the actual output preview. Confirm amounts are
   labelled synthetic executed output, not validated financial revenue.
7. Examine dbt tests, quality checks, reconciliation, and the Independent
   Evidence Verification panel separately. Note anything marked unavailable.
8. Reopen the same run from history. Confirm the workflow ids did not change
   and no second run started.
9. Repeat steps 1, 4, and 5 in a narrow (about 390 px) browser window.

Record the run id and what you accepted or rejected. Do not mark business
correctness validated.

## Subsequent data-correctness cases

These cases are **not run** and **not passed**. Expected outcomes are defined
from `docs/DEMO_COMPANY.md` and the Frontier review, independently of whatever
SQL the generator emits. Unresolved definitions stay questions.

### Currency separation

Tiny invoices contain EUR, USD, GBP, and the literal codes `eur` and `€`.
The current mart adds those amounts into `invoiced_amount` and `paid_amount`
with no FX conversion.

Independent expectation: amounts are reported per currency, or converted with a
dated rate table and a written policy. A single mixed sum is not financial
revenue.

Open question: which base currency, which rate source, and which rate date
(invoice date, payment date, or a fixed demo date)? Do not invent a rate.

### Refund treatment

The tiny fixture has 190 refund rows totalling 103447.13. Refunds are staged
and are not subtracted from `paid_amount`.

Independent expectation: if the business measure is net cash, refunds reduce
the paid measure. If the measure is gross collections, refunds stay a separate
column and the page says so.

Open question: is `paid_amount` gross receipts or net of refunds? Which refund
statuses count?

### Row grain

The business grain in the demo company notes is one row per customer and day,
with invoiced, paid, refunded, open, active subscriptions, and MRR. The unknown
customer member is specified as `-1`.

Independent expectation: one row per `customer_sk` and `date_day`, refunded and
open amounts present when defined, and facts that do not match a customer use
the unknown member.

Open question: which date (invoice date, payment date, or both) defines
`date_day` when a payment lands on a later day?

### Duplicate handling

Payments are deduplicated on `invoice_id` plus `payment_ref`. Account
survivorship keeps the latest `updated_at` and does not apply `IS_DELETED`.
The demo company P1 note says deleted CRM accounts are filtered. Tiny has 2
deleted account rows.

Independent expectation: duplicate payment keys collapse to one fact row.
Deleted accounts do not appear in the customer dimension if P1 is the rule.

Open question: does “latest `updated_at`” win even when that row is deleted, or
must a non-deleted row win when one exists?

## Limitations

- One fixed scenario. The backend ignores arbitrary request text.
- No uploads, no user SQL, no new repair class, no RAW writes.
- Output previews are capped (20 rows, 12 columns) and sanitized. They are a
  snapshot of the synthetic mart, not a warehouse query after restart.
- While a run is in progress, workflow ids are not known. The page shows a
  running indicator and refreshes. It does not invent stage progress.
- The in-process event bus is not the history source. Completed runs show
  persisted audit event types only.
