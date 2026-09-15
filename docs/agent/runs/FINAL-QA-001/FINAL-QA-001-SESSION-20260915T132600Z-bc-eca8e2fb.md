# Run report — FINAL-QA-001

| Field | Value |
|-------|-------|
| Task ID | FINAL-QA-001 |
| Session ID | FINAL-QA-001-SESSION-20260915T132600Z-bc-eca8e2fb |
| Environment | CURSOR_CLOUD |
| Model | Cursor Grok 4.6 |
| Reasoning level | xhigh |
| Branch | cursor/interview-evaluation-hardening-8bc5 |
| Base commit | 8324ef56d4c871c3f1303e28b722f2d78c163e98 |
| Implementation commit | `3f51b4a2ba3a83863ca9c8d6196ca399e3b72259` |
| CI remediation commits | `cfa4882ec4a4ff47f1dddaca0541acd6b17ce773`, `08d5a0daa9db52d7160e8a0c7b6106fd2ddc79ea` |
| Synced main | `a5f9b6900f08cd27fc43ef283f0cae1c5c395f0c` |
| Report status | SUCCESS |
| PR number | 24 |

## Goal

Determine whether the accepted Interview MVP is reliable enough to present.
Build a final evaluation and adversarial test layer. Fix only in-scope defects.
Do not add product scope, repair classes, or vendors. Do not merge.

## Scope completed

- Deterministic evaluation contracts and scorecard (`PASS` / `FAIL` / `NOT_TESTED`, no LLM judge).
- Adversarial tests for happy path, repeatability, failure injection, safety,
  persistence/recovery, evidence tamper, provenance, least privilege, benchmark
  classification, performance hang detection, and known limitations.
- In-scope fail-closed fixes listed in `docs/evaluation/FINAL_QA_001.md`.
- Offline evaluation verdict: `PRESENTABLE_OFFLINE_CREDENTIAL_GATED`.
- CI remediation: Pytest 9 nested `pytest_plugins` removed; evaluation fixtures
  re-exported; `tests/evaluation/test_evaluation_benchmark.py` unique basename;
  branch merged with SHOWCASE-001 `main` at `a5f9b69`.

## Files changed

Created:

- `src/aide/domain/evaluation.py`
- `src/aide/app/evaluation/**`
- `tests/evaluation/**`
- `tests/unit/evaluation/test_scorecard.py`
- `tests/unit/evaluation/test_pytest9_conftest.py`
- `docs/evaluation/README.md`
- `docs/evaluation/FINAL_QA_001.md`
- `docs/agent/runs/FINAL-QA-001/FINAL-QA-001-SESSION-20260915T132600Z-bc-eca8e2fb.md`

Modified:

- `src/aide/verification/evaluate.py`
- `src/aide/app/benchmarking/evidence.py`
- `src/aide/app/supervisor.py`
- `src/aide/app/gateway.py`
- `src/aide/connectors/dbt/fake.py`
- `tests/unit/verification/test_verifier.py`
- `tests/integration/interview/test_evidence_bundle_persistence.py`
- `.ai/TASKS.md`
- `docs/EVALUATION_STRATEGY.md`
- `docs/agent/runs/README.md` (keeps SHOWCASE-001 and FINAL-QA-001 rows)

Removed: nested `pytest_plugins` in `tests/evaluation/conftest.py`

Renamed: `tests/evaluation/test_benchmark.py` → `tests/evaluation/test_evaluation_benchmark.py`

## Tests executed

- `uv run pytest tests/unit/evaluation tests/unit/verification/test_verifier.py tests/evaluation/test_safety.py tests/evaluation/test_tamper.py tests/evaluation/test_provenance.py tests/evaluation/test_limitations.py tests/evaluation/test_least_privilege.py tests/unit/repair/test_validate_repair.py tests/integration/interview/test_evidence_bundle_persistence.py -q --tb=short`
- `uv run pytest tests/evaluation tests/unit/evaluation -q --tb=short`
- `uv run pytest tests/evaluation/test_happy_path.py --durations=5 -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests asgi.py`
- `uv run lint-imports`
- `uv run alembic upgrade head`
- `uv run alembic check`
- `uv run pytest`
- `uv run pytest tests/evaluation tests/unit/evaluation -q --tb=short`
- `/tmp/gitleaks detect --source . --config .gitleaks.toml --verbose --redact --no-banner`

## Test results

- Focused unit/safety/tamper/provenance: passed.
- Evaluation folder (initial): 55 passed.
- CI remediation full suite: `uv run pytest` **556 passed, 8 skipped**, 10 warnings, 566.76s, exit 0 (Pytest 9.1.1).
- Focused evaluation after remediation: `tests/evaluation tests/unit/evaluation` **56 passed**, exit 0.
- Happy path duration: 6.77s offline closed loop.
- Ruff lint and format: passed (345 files formatted).
- Mypy: passed, 309 source files.
- Import-linter: 13 contracts kept, 0 broken.
- Alembic upgrade head: applied; `alembic check`: no new upgrade operations.
- Gitleaks 8.24.2: no leaks found (183 commits scanned).

## Validation

Scorecard categories are PASS except live least-privilege remains optional
`NOT_TESTED`. Readiness is `PRESENTABLE_OFFLINE_CREDENTIAL_GATED`. No LLM judge.

## CI remediation

GitHub CI failed collection under Pytest 9.1.1 because
`tests/evaluation/conftest.py` declared nested `pytest_plugins`.
The fixtures `migrated_database`, `database_engine`, and `session_factory` are
now re-exported from `tests.integration.conftest`. Full-suite collection also
required renaming `tests/evaluation/test_benchmark.py` so it does not share a
module basename with `tests/integration/interview/test_benchmark.py`.

`origin/main` at `a5f9b6900f08cd27fc43ef283f0cae1c5c395f0c` (SHOWCASE-001) was
merged. Recruiter README and showcase wording were kept. `.ai/TASKS.md`,
`docs/EVALUATION_STRATEGY.md`, and `docs/agent/runs/README.md` contain both
SHOWCASE-001 and FINAL-QA-001 content. GitHub reports PR 24 `mergeable=MERGEABLE`
and this branch contains `origin/main`.

## Errors

None remaining in the accepted Interview MVP offline path after the listed fixes.

## Blockers

None for offline presentation. Live Snowflake/dbt Interview smoke is credential
gated on this host. GitHub `mergeStateStatus` may remain `UNSTABLE` until the
post-remediation CI checks finish.

## Important decisions

- Evaluation is an additive test/scorecard layer, not a new product architecture.
- MOCK workflows must stay MOCK; mixed REAL/MOCK always fails.
- Interview failures persist terminal `FAILED` or `BLOCKED`.
- Recovered EXECUTE intents must not remain `DISPATCHED`.

## Architecture deviations

None.

## Open questions

None.

## Human action required

Review and merge PR 24. Optionally run credentialed AT-24 live smoke on a host
that already has Snowflake env vars. Do not paste secrets.

## Recommended next task

Human review of PR 24. Live credentialed smoke remains optional and gated.

## Parallel coordination

- **Declared file ownership:** evaluation contracts/tests, fail-closed Interview
  Supervisor/Gateway/verifier/dbt-fake recovery, `docs/evaluation/`
- **Forbidden files:** frontend, new connectors, GRANT/REVOKE, VANTARA_RAW mutation
- **Dependencies:** MVP001–MVP004 merged
- **Integration order:** None; single writer
