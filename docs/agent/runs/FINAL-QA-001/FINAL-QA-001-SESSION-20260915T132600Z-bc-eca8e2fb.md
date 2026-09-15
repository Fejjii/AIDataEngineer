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

## Files changed

Created:

- `src/aide/domain/evaluation.py`
- `src/aide/app/evaluation/**`
- `tests/evaluation/**`
- `tests/unit/evaluation/test_scorecard.py`
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
- `docs/agent/runs/README.md`

Removed: None

## Tests executed

- `uv run pytest tests/unit/evaluation tests/unit/verification/test_verifier.py tests/evaluation/test_safety.py tests/evaluation/test_tamper.py tests/evaluation/test_provenance.py tests/evaluation/test_limitations.py tests/evaluation/test_least_privilege.py tests/unit/repair/test_validate_repair.py tests/integration/interview/test_evidence_bundle_persistence.py -q --tb=short`
- `uv run pytest tests/evaluation tests/unit/evaluation -q --tb=short`
- `uv run pytest tests/evaluation/test_happy_path.py --durations=5 -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests asgi.py`
- `uv run lint-imports`
- `uv run alembic check`
- `uv run pytest tests/unit -q --tb=line`
- `uv run pytest tests/integration tests/connectors tests/security tests/contracts -o addopts='--strict-markers' -q --tb=line -m "not snowflake_live and not dbt_live"`
- `uv run pytest tests/connectors/contract/test_interview_live_gated.py tests/integration/interview/test_live_governed.py tests/connectors/contract/test_interview_live_smoke.py -q --tb=line`
- `/tmp/gitleaks detect --source . --config .gitleaks.toml --verbose --redact --no-banner`

## Test results

- Focused unit/safety/tamper/provenance: passed.
- Evaluation folder: 55 passed.
- Happy path duration: 6.77s offline closed loop.
- Ruff lint and format: passed.
- Mypy: passed, 308 source files.
- Import-linter: 13 contracts kept, 0 broken.
- Alembic check: no new upgrade operations.
- Unit tests: passed.
- Non-live integration/connector/security/contract: 206 passed, 8 deselected.
- Live credential-gated: 10 passed, 2 skipped (`snowflake_live` / `dbt_live`; env vars unset).
- Gitleaks 8.24.2: no leaks found (174 commits scanned).

## Validation

Scorecard categories are PASS except live least-privilege remains optional
`NOT_TESTED`. Readiness is `PRESENTABLE_OFFLINE_CREDENTIAL_GATED`. No LLM judge.

## Errors

None remaining in the accepted Interview MVP offline path after the listed fixes.

## Blockers

None for offline presentation. Live Snowflake/dbt Interview smoke is credential
gated on this host.

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
