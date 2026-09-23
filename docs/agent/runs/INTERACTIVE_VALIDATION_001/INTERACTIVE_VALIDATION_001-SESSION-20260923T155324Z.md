# Run report — INTERACTIVE_VALIDATION_001

| Field | Value |
|-------|-------|
| Task ID | INTERACTIVE_VALIDATION_001 |
| Session ID | INTERACTIVE_VALIDATION_001-SESSION-20260923T155324Z |
| Environment | CURSOR_CLOUD |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | `feat/interactive_validation_001` |
| Base commit | `84373997696fc99e81aee16207c0d17f11e2cf86` |
| Implementation commit | `0a99c890f813ce64cb2775db657f7255f8162574` |
| Report status | SUCCESS |
| PR number | 36 |

## Goal

Give the operator an authenticated browser console that runs the implemented synthetic Interview scenario, shows actual inputs and persisted outputs, and supports human acceptance. Human acceptance itself remains NOT_RUN.

## Scope completed

- Server-rendered console inside the existing FastAPI process and image.
- Operator password, HttpOnly session cookie, CSRF on mutations, no browser token storage.
- Anonymous `POST /v1/sessions`, `POST /v1/workflows`, and workflow event streaming stay unregistered unless `AIDE_LEGACY_ANONYMOUS_ROUTES=1`.
- Fixed scenario, objective, synthetic label, selected tables, schema, and capped masked fixture samples. No request box and no upload.
- Run starts the existing two-workflow benchmark. Refresh uses GET. A busy runner returns 409.
- History reads PostgreSQL artifacts. A bounded sanitized preview is captured during the fake dbt execution and stored as `operator_console_snapshot`.
- Allowlisted exports, escaped failure text, and unavailable (not PASS) when evidence is missing.
- Execution status, evidence consistency, and business correctness `NOT_VALIDATED` stay separate. Currency, refund, and history limitations are displayed. Generated SQL is unchanged.
- Operator instructions, human acceptance script, and subsequent correctness cases in `docs/ops/OPERATOR_CONSOLE.md`.

## Files changed

Created:

- `docs/ops/OPERATOR_CONSOLE.md`
- `src/aide/api/console_ports.py`
- `src/aide/api/console_routes.py`
- `src/aide/api/templates/base.html`
- `src/aide/api/templates/denied.html`
- `src/aide/api/templates/home.html`
- `src/aide/api/templates/login.html`
- `src/aide/api/templates/run.html`
- `src/aide/app/console/__init__.py`
- `src/aide/app/console/present.py`
- `src/aide/app/console/service.py`
- `src/aide/app/console/snapshot.py`
- `src/aide/app/console/sources.py`
- `src/aide/persistence/alembic/versions/b7e4c1a09d55_operator_console_runs.py`
- `src/aide/persistence/console.py`
- `tests/integration/test_operator_console.py`
- `tests/unit/api/test_legacy_routes_disabled.py`
- `tests/unit/console/test_console_evidence.py`

Modified:

- `.ai/DECISIONS.md`
- `.ai/TASKS.md`
- `.env.example`
- `Dockerfile`
- `README.md`
- `asgi.py`
- `docker-compose.yml`
- `docs/ops/SYNTHETIC_CLOUD_DEMO.md`
- `src/aide/api/app.py`
- `src/aide/app/benchmarking/runner.py`
- `src/aide/app/benchmarking/service.py`
- `src/aide/app/sessions.py`
- `src/aide/connectors/dbt/fake.py`
- `src/aide/domain/benchmark.py`
- `src/aide/persistence/models.py`
- `src/aide/persistence/repositories.py`
- `tests/integration/conftest.py`
- `tests/integration/test_http_auth.py`

Removed:

- None

The run-report index update is in the report commit, not in the implementation commit.

## Tests executed

From `/workspace`, against local PostgreSQL `aide_dev`. No Snowflake, dbt Cloud, Railway, or full evaluation campaign.

```text
uv run ruff check src/aide/api src/aide/app/console src/aide/domain/benchmark.py
uv run mypy src/aide
uv run lint-imports
uv run pytest -q tests/unit/console tests/unit/api/test_legacy_routes_disabled.py
uv run pytest -q tests/integration/test_operator_console.py tests/integration/test_http_auth.py
uv run pytest -q tests/unit/deploy/test_synthetic_demo_packaging.py tests/integration/interview/test_restart_persistence.py tests/unit/benchmark
uv run pytest -q tests/security/test_synthetic_demo_boundaries.py tests/unit/deploy/test_synthetic_demo_packaging.py
```

## Test results

- Ruff: all checks passed.
- Mypy: no issues found in 221 source files.
- Import-linter: 13 contracts kept, 0 broken.
- Unit console and legacy-route tests: 7 passed.
- Operator console and HTTP auth integration: 16 passed.
- Packaging, interview restart persistence, and benchmark unit tests: 25 passed.
- Security boundary and packaging tests: 17 passed.

The real-scenario integration test runs `SyntheticInterviewDemoService` twice-workflow path and expects completed status, staging SQL, `NOT_VALIDATED`, and a CSV export.

## Validation

Browser, against `uv run uvicorn asgi:app --host 127.0.0.1 --port 8000` with the synthetic database. Legacy `POST /v1/sessions` returned 404. Health returned 200.

- Desktop viewport about 1220×800.
- Mobile viewport 390×924 via browser responsive mode.
- Signed in, inspected masked sources, started one run, waited for completion, reopened the same run from history.
- Run id `7d50f463-9224-4cdf-91a4-a30566cb6334` status `completed` in `operator_console_runs`.
- Workflow ids `f980ba81-642f-42fb-a584-8ab36b42dd27` and `d5b758a5-ce04-43c3-864d-9594d8e5a9a1`.
- One `operator_console_snapshot` artifact plus verifier, quality, repair, and test artifacts for both workflows.
- On-screen: scenario id, synthetic label, `NOT_VALIDATED`, currency and refund limitations, masked account name, `stg_billing__invoices.sql`, preview columns `customer_sk`, `date_day`, `invoiced_amount`, `paid_amount`, drift `INVOICE_STATUS` to `STATUS`, evidence consistency PASS.
- Reopen kept the same run id. No second run was started by refresh.
- A cookie-less browser window was not opened. Unauthenticated denial with no database writes is covered by `tests/integration/test_operator_console.py`.

Human acceptance script: USER_ACCEPTANCE_NOT_RUN.

Subsequent correctness cases (currency separation, refund treatment, row grain, duplicate handling): defined in `docs/ops/OPERATOR_CONSOLE.md` and not executed. They are not passed.

## Errors

None that remain. Import-linter initially rejected API imports of the concrete console service. The HTTP layer now depends on protocols in `aide.api.console_ports`. Source samples initially looked at the wrong fixture path; they now use the tiny `v1` CSV path.

## Blockers

None for review. Human acceptance is still required before anyone treats the scenario as accepted.

## Important decisions

- The console is Jinja inside FastAPI. It does not implement DE 016.
- This run used Grok 4.7. It is not the Claude Fable 5.1 model recorded for the Frontier PR 34 audit.
- Output preview is captured while the in-memory fake dbt connection is alive and then stored. It is not a canned expected row set, and it is excluded from the benchmark fingerprint.
- Interrupted `running` rows are failed on process start. The message says completion evidence is unavailable.
- Console sessions are OPERATOR only. The benchmark still creates its own internal principal.

## Architecture deviations

Additive under DE-ADR-026. Documented in `.ai/DECISIONS.md`. No SPA, no new vendor connector, no SQL or repair-class change.

## Open questions

Recorded for the later correctness cases, not answered here:

- Which base currency, rate source, and rate date apply if mixed amounts must be converted?
- Is `paid_amount` gross receipts or net of refunds, and which refund statuses count?
- Which date defines `date_day` when a payment lands on a later day?
- Does latest `updated_at` win when that account row is deleted?

## Human action required

- Development Control reviews and merges. This agent does not merge.
- Do not deploy from this run. When deploying the existing Railway service later: set `AIDE_OPERATOR_PASSWORD` (12+ characters), set `AIDE_SESSION_COOKIE_SECURE=1`, leave `AIDE_LEGACY_ANONYMOUS_ROUTES` unset or `0`, and let the entrypoint apply Alembic `b7e4c1a09d55`. Confirm `POST /v1/sessions` is 404.
- Sofien runs the acceptance script in `docs/ops/OPERATOR_CONSOLE.md`. Status stays USER_ACCEPTANCE_NOT_RUN until that is done.
- Do not treat verifier PASS or benchmark PASS as validated financial revenue.

## Recommended next task

Human acceptance of this console, then a separate task for the four data-correctness cases if the business definitions are answered. Do not start interview preparation from this run.

## Parallel coordination

- **Declared file ownership:** operator console routes, templates, `aide.app.console`, `operator_console_runs`, operator docs, and the tests listed above.
- **Forbidden files:** live Railway config, vendor credentials, generated mart SQL, repair allow-list semantics.
- **Dependencies:** `origin/main` at `84373997696fc99e81aee16207c0d17f11e2cf86`. No other writer.
- **Integration order:** this branch alone. Merge authority is Development Control.
