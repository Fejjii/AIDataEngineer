# Operator console

**Task:** INTERACTIVE_VALIDATION_001  
**Audience:** the operator who accepts the synthetic Interview scenario  
**Scope:** one authenticated browser page inside the existing FastAPI process.

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

## Human acceptance script

**Status: USER_ACCEPTANCE_NOT_RUN.** Automated checks do not replace this script.
Sofien completes it on the deployed or local synthetic process.

1. Sign in at `/console/login`.
2. Inspect the scenario, objective, synthetic label, and masked source samples.
3. Start a run. Confirm the page says the benchmark executes two workflows and
   does not invent stages.
4. When the run completes, inspect generated SQL and the actual output preview.
   Confirm amounts are not labelled validated financial revenue.
5. Inspect drift diagnosis, original SQL, and repaired SQL.
6. Examine individual tests, quality outcomes, and verifier evidence. Note
   anything marked unavailable.
7. Reopen the same run from history. Confirm the workflow ids did not change
   and no second run started.

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
