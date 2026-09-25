# SHOWCASE_SMOKE_001 — Data Pilot AI Interview MVP

**Audience:** recruiters and operators walking the synthetic console  
**Automated proof:** `tests/integration/test_showcase_smoke.py`  
**Summary helper:** `tests/evaluation/showcase_summary.py`

This smoke proves one recruiter-facing story: an authenticated operator sees the
synthetic estate, starts the fixed Interview benchmark, and can reopen the same
completed run. It does not prove generic enterprise autonomy, financial
correctness, live Snowflake, or a production deployment.

## What the smoke proves

- Authenticated operator access to the existing FastAPI console
- The synthetic estate and its source schemas are visible before a run
- One benchmark run can start and finish
- Persisted evidence exists for the Digital Twin snapshot, generated models and
  SQL, dbt execution, tests, and quality checks
- Schema drift is detected as `SCHEMA_MISMATCH`, mapping `INVOICE_STATUS` to
  `STATUS`
- One bounded repair is applied and post-repair validation succeeds
- An Independent Verifier verdict, evidence completeness, and a determinism
  comparison are recorded from persisted artifacts
- History reopens that run and does not create another one
- Anonymous legacy routes stay unavailable
- Business correctness stays `VALIDATED_SYNTHETIC_CONTRACT`

## What it does not prove

- Verifier `PASS` is evidence consistency for this schema-drift repair. It is
  not a business-correctness `PASS`.
- Mixed-currency amounts, refunds, and customer history are not validated
  financial results.
- No live Snowflake, dbt Cloud, Railway, GitHub delivery, or production action
  is exercised.
- Metric counts are read from the run that just finished. They are not
  contractual constants in this smoke.

## Automated smoke

PostgreSQL must already be migrated. The test uses the same database fixture as
the other integration tests (`AIDE_TEST_DATABASE_URL`, otherwise the local
`aide_dev` DSN). No Snowflake credentials are required.

```bash
uv run pytest -q tests/evaluation/test_showcase_summary.py tests/integration/test_showcase_smoke.py
```

The integration test signs in over the ASGI app, reads the source catalog,
starts `POST /console/runs`, waits for the real synthetic benchmark, and
reloads the run with `GET`. It asserts the allowlisted artifact bodies and the
typed run page. Missing evidence stays `unavailable`. After the assertions,
the test writes one summary block to the process stdout:

```text
run status: completed
workflow outcome: VERIFIED
Digital Twin: snapshot <id> assets <count>
models: <n> model files
tests: <passed>/<total> passed; aggregate true
quality: passed=true checks=<n>
incident: SCHEMA_MISMATCH INVOICE_STATUS → STATUS
repair: applied=true count=1 path=models/staging/stg_billing__invoices.sql
verifier: PASS
evidence: complete=true completeness=<pct>
determinism: true
business correctness: VALIDATED_SYNTHETIC_CONTRACT
```

`<id>`, `<count>`, `<n>`, `<passed>`, `<total>`, and `<pct>` come from the
persisted run. The test fails if those fields are missing. It does not treat a
verifier `PASS` as business correctness.

One console run stores two workflow ids. That pair is the benchmark's
determinism comparison, not a second operator run.

## Human showcase runbook

Use the operator console described in [`../ops/OPERATOR_CONSOLE.md`](../ops/OPERATOR_CONSOLE.md).
Do not change generated SQL, repair behavior, or the page styling for this walkthrough.

1. Set `AIDE_OPERATOR_PASSWORD` to at least 12 characters. Leave
   `AIDE_LEGACY_ANONYMOUS_ROUTES` unset.
2. Open `/console/login` and sign in. An anonymous visit to `/console` returns
   to the login page.
3. On `/console`, confirm the synthetic database, source schemas, column names,
   and types. Confirm business correctness reads `VALIDATED_SYNTHETIC_CONTRACT`.
4. Start **Run Data Engineering Workflow** once. Refreshing the run page must
   not start another run.
5. When the run completes, read the engineering loop from the persisted page:
   Digital Twin snapshot, generated SQL, dbt tests, quality checks, the
   `INVOICE_STATUS` → `STATUS` incident, one repair, revalidation, verifier
   verdict, evidence completeness, and determinism.
6. Return to `/console` and open the same run from history. The history list
   still has that one run.
7. Confirm `POST /v1/sessions`, `POST /v1/workflows`, and workflow event
   streaming are not available.
8. Read the verifier line and the business-correctness line as separate
   statuses. Do not tell a recruiter that verifier `PASS` means the revenue
   numbers are correct.

## Result summary fields

| Field | Source | Separate from |
|---|---|---|
| run status | console run row | verifier verdict |
| workflow outcome | benchmark snapshot | business correctness |
| Digital Twin | `twin_snapshot` artifact | model SQL |
| models | snapshot model files | a hardcoded file count |
| tests | `dbt_tests` plus individual test rows | quality checks |
| quality | `quality_results` | verifier checks |
| incident | drift observation and repair proposal | a successful repair |
| repair | `repair_application` and repair count | post-repair validation |
| verifier | `verifier_verdict` artifact | business correctness |
| evidence | evidence completeness on the snapshot | a missing bundle |
| determinism | `determinism_equivalent` on the snapshot | a second console run |
| business correctness | constant `VALIDATED_SYNTHETIC_CONTRACT` on the page | verifier `PASS` or `FAIL` |

## Final verdict

`SHOWCASE_SMOKE_PASS` means the automated smoke and the checks listed in the
task validation section passed on this branch.

`SHOWCASE_SMOKE_FAIL` means one of those checks failed, or a required persisted
field was unavailable. A verifier `PASS` alone is not this verdict.
