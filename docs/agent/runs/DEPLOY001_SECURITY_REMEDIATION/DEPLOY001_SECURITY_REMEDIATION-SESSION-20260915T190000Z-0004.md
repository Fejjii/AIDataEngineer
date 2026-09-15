# Run report — DEPLOY001_SECURITY_REMEDIATION

| Field | Value |
|-------|-------|
| Task ID | DEPLOY001_SECURITY_REMEDIATION |
| Session ID | DEPLOY001_SECURITY_REMEDIATION-SESSION-20260915T190000Z-0004 |
| Environment | CURSOR_CLOUD |
| Model | Grok 4.6 |
| Reasoning level | high |
| Branch | `deploy/synthetic_cloud_demo` |
| Base commit | `289203b3bbe4cf4854ebd6827afd288b2728ad48` |
| Implementation commit | `714a95083a3f4c1635fc47cdffa62a7b079e38cf` |
| Report status | SUCCESS |
| PR number | 26 |
| Final verdict | SECURE_DEFAULTS_READY_DO_NOT_MERGE |

## Goal

Make the synthetic cloud deployment secure by default while preserving the
accepted Interview architecture and validated demo behavior. Do not merge.

## Scope completed

1. PostgreSQL is not published to the host. The app uses the Compose network
   hostname `postgres`. CI smoke uses `docker compose exec` and inspects
   `HostConfig.PortBindings`.
2. Removed the deterministic `POSTGRES_PASSWORD` fallback from
   `scripts/synthetic_demo.sh`. Compose fails closed unless the value is set in
   the environment or `.env`. CI smoke generates an ephemeral random password at
   runtime.
3. HTTP demo defaults to disabled. Enabling `AIDE_SYNTHETIC_DEMO_HTTP` without
   a nonempty `AIDE_SYNTHETIC_DEMO_TOKEN` fails closed at startup. CLI demo does
   not use this token.
4. Application host bind defaults to `127.0.0.1` via `AIDE_HTTP_BIND`. Public
   bind is explicit and still requires the demo token when HTTP demo is enabled.
5. Dockerfile has one canonical `ENV` block.

## Files changed

Created: `src/aide/api/demo_http.py`, `tests/unit/api/test_demo_http.py`, this
run report.

Modified: `.ai/DECISIONS.md`, `.ai/TASKS.md`, `.env.example`, `Dockerfile`,
`asgi.py`, `docker-compose.yml`, `docs/ops/SYNTHETIC_CLOUD_DEMO.md`,
`scripts/ci_compose_smoke.sh`, `scripts/synthetic_demo.sh`,
`src/aide/api/app.py`, `tests/security/test_synthetic_demo_boundaries.py`,
`tests/unit/api/test_interview_demo.py`,
`tests/unit/deploy/test_synthetic_demo_packaging.py`.

Removed: None.

## Tests executed

- `uv run pytest tests/unit/api/test_demo_http.py tests/unit/api/test_interview_demo.py tests/unit/deploy/test_synthetic_demo_packaging.py tests/security/test_synthetic_demo_boundaries.py tests/security/test_leakage.py tests/unit/api/test_readyz.py tests/unit/benchmark/test_demo_summary.py tests/unit/cli/test_cli_help.py tests/unit/verification/test_verifier.py tests/evaluation/test_safety.py tests/evaluation/test_least_privilege.py tests/integration/interview/test_benchmark.py -q --tb=short`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests asgi.py`
- `uv run lint-imports`
- `uv run alembic upgrade head`
- `uv run alembic check`
- `uv run pytest -q --tb=line`
- `uv run aide interview demo`
- `uv run aide interview demo --json`
- `/tmp/gitleaks detect --source . --config .gitleaks.toml --verbose`
- GitHub Actions `CI` run `35013798575` on `714a950`

## Test results

- Focused pytest: 78 passed, 0 failed
- Quality gates: ruff, format, mypy (320 files), import-linter (13 kept,
  including Independent verifier cannot import execution or writers), alembic
  check PASS
- Full non-live pytest: 590 passed, 8 skipped, 0 failed (598 collected)
- CLI demo: Independent Verifier PASS, determinism PASS, evidence 100%, repair
  applied exactly once, human interventions 0
- CLI demo JSON: `benchmark_verdict=PASS`, `live_smoke=CREDENTIAL_GATED`, no
  secret names in the payload
- gitleaks: no leaks found (192 commits)
- GitHub CI: Lint and types, Secret scan, Tests and migrations, Docker build all
  pass on `714a950`

## Validation

1. Compose postgres service has no `ports:` mapping; smoke log:
   `PostgreSQL host port publication is absent`
2. No deterministic database password in `scripts/synthetic_demo.sh`;
   `./scripts/synthetic_demo.sh up` fails closed without `POSTGRES_PASSWORD`
3. HTTP demo disabled by default (`AIDE_SYNTHETIC_DEMO_HTTP=0`); CI smoke:
   `HTTP demo is disabled by default` (POST returns 404)
4. HTTP demo cannot start or execute without a token when enabled
   (`HttpDemoMisconfiguredError`; helper script fails closed; 401 without header)
5. Token-authenticated demo still succeeds (`X-AIDE-Demo-Token`)
6. CLI demo succeeds without Snowflake credentials and without the HTTP token
7. No secret values in health/demo responses, CLI JSON, or gitleaks
8. Production and staging remain disabled
9. Repair count remains exactly one
10. Independent Verifier remains read-only (import-linter contract kept)

## Errors

GitHub Docker smoke on `c7cbd79` failed because `docker compose port postgres 5432`
treated an unpublished image `EXPOSE` as a host mapping. Fixed by inspecting
`HostConfig.PortBindings` in `714a950`. Re-run `35013798575` passed.

## Blockers

None for this security remediation. Standing public URL still requires a human
to authenticate a container host. Merge to `main` is a human action.

## Important decisions

Fail closed at application startup when HTTP demo is enabled without a token,
rather than mounting an anonymous route. Keep uvicorn listening on `0.0.0.0`
inside the container; restrict host publication with Compose `AIDE_HTTP_BIND`.

## Architecture deviations

None. Additive under DE-ADR-026. No new services.

## Open questions

None.

## Human action required

Review PR 26. Do not merge from an agent. Optionally authenticate one container
host and set local secrets (`POSTGRES_PASSWORD`, `AIDE_CSRF_SECRET`, and
`AIDE_SYNTHETIC_DEMO_TOKEN` if HTTP demo is enabled). Do not paste values into
chat.

## Recommended next task

Human review of PR 26. Optional authenticated host deploy using
`docs/ops/SYNTHETIC_CLOUD_DEMO.md`.

## Parallel coordination

- **Declared file ownership:** synthetic demo Compose, scripts, ASGI HTTP demo
  policy, packaging/security tests, `docs/ops/SYNTHETIC_CLOUD_DEMO.md`
- **Forbidden files:** `.ai/private/**`, `.ai/local/**`, root handoffs, production
  config
- **Dependencies:** DEPLOY001_SYNTHETIC_CLOUD_DEMO package on this branch
- **Integration order:** None
