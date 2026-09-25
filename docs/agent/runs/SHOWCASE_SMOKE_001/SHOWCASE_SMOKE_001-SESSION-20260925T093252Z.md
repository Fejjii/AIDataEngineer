# Run report — SHOWCASE_SMOKE_001

| Field | Value |
|-------|-------|
| Task ID | SHOWCASE_SMOKE_001 |
| Session ID | SHOWCASE_SMOKE_001-SESSION-20260925T093252Z |
| Environment | CURSOR_CLOUD |
| Model | Grok 4.7 |
| Reasoning level | high |
| Branch | `cursor/showcase-smoke-001-56bf` |
| Base commit | `b84edc3acf92a1608a230473f787deebb44060fb` |
| Implementation commit | `f19339266e913c0fb3063802218236215706157d` |
| Report status | SUCCESS |
| PR number | 39 |

## Goal

Add one deterministic showcase smoke for the Data Pilot AI Interview MVP that proves the recruiter-facing operator story from persisted evidence.

## Scope completed

- Integration smoke drives the existing FastAPI operator console, PostgreSQL test database, synthetic fixtures, and real Interview benchmark.
- Assertions read allowlisted artifact bodies and the typed run page.
- Summary helper leaves missing evidence as `unavailable` and keeps verifier PASS separate from business correctness `NOT_VALIDATED`.
- Human runbook at `docs/evaluation/SHOWCASE_SMOKE_001.md`.
- Final verdict: `SHOWCASE_SMOKE_PASS`.

Observed summary from `tests/integration/test_showcase_smoke.py` on this run:

```text
run status: completed
workflow outcome: VERIFIED
Digital Twin: snapshot 467f1d82-fac5-4abf-ba2f-f16be069cd8f assets 102
models: 22 model files
tests: 23/23 passed; aggregate true
quality: passed=true checks=25
incident: SCHEMA_MISMATCH INVOICE_STATUS → STATUS
repair: applied=true count=1 path=models/staging/stg_billing__invoices.sql
verifier: PASS
evidence: complete=true completeness=100
determinism: true
business correctness: NOT_VALIDATED
```

Counts and the snapshot id came from that persisted run. They are not new contract constants.

## Files changed

Created:

- `docs/evaluation/SHOWCASE_SMOKE_001.md`
- `tests/evaluation/showcase_summary.py`
- `tests/evaluation/test_showcase_summary.py`
- `tests/integration/test_showcase_smoke.py`

Modified:

- `docs/evaluation/README.md`

Removed:

- None

The run-report index update is in the report commit, not in the implementation commit.

## Tests executed

From `/workspace`. No Snowflake.

```text
uv run ruff check tests/evaluation/showcase_summary.py tests/evaluation/test_showcase_summary.py tests/integration/test_showcase_smoke.py
uv run ruff format --check tests/evaluation/showcase_summary.py tests/evaluation/test_showcase_summary.py tests/integration/test_showcase_smoke.py
uv run mypy src/aide
uv run pytest -q tests/evaluation/test_showcase_summary.py tests/integration/test_showcase_smoke.py
uv run pytest -q tests/integration/test_operator_console.py
uv run pytest -q tests/security tests/unit/api/test_legacy_routes_disabled.py
```

## Test results

- Ruff check: all checks passed.
- Ruff format: 3 files already formatted.
- Mypy: no issues found in 221 source files.
- Showcase summary unit tests and showcase smoke: passed. Smoke printed the summary above.
- Operator console integration tests: 6 passed.
- Security boundaries and legacy-route unit test: 7 passed. Starlette deprecation warnings only.

## Validation

- Authenticated console start, synthetic estate and schemas, one completed benchmark, persisted twin, models, SQL, dbt execution, tests, quality, `SCHEMA_MISMATCH`, `INVOICE_STATUS` to `STATUS`, one repair, post-repair validation, verifier verdict, evidence completeness, determinism, history reopen without a new run, anonymous legacy routes 404, business correctness `NOT_VALIDATED`.
- Snowflake was not run. No credentialed path was changed.
- UI templates, generated mart SQL, quality semantics, Supervisor, repair, connectors, and Railway configuration were not modified.

## Errors

None

## Blockers

None

## Important decisions

- The smoke uses the existing operator console and synthetic benchmark instead of a browser runner.
- One console run persists two workflow ids because that is the benchmark determinism pair.
- Metric counts are asserted against persisted rows, not copied in as expected literals.
- Verifier `PASS` and business correctness `NOT_VALIDATED` stay separate fields.

## Architecture deviations

None

## Open questions

None

## Human action required

Review the pull request. Do not merge from this run.

## Recommended next task

None

## Parallel coordination

- **Declared file ownership:** focused integration and evaluation tests, `docs/evaluation/SHOWCASE_SMOKE_001.md`, `docs/evaluation/README.md` index row, this run report.
- **Forbidden files:** UI templates, generated mart SQL, quality business semantics, Supervisor, repair, connectors, Railway deployment configuration.
- **Dependencies:** Interview MVP and operator console already on `main`.
- **Integration order:** None
