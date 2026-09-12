# Branch protection — required GitHub checks after DE 003

**Status:** Documentation only. Development Control applies these settings on `main` after
DE 003 merges. Agents must not change GitHub repository settings.

**Workflow file:** `.github/workflows/ci.yml`  
**Workflow name:** `CI`

## Required status checks

Configure branch protection on `main` to require these checks before merge:

| Check name (exact) | Job | Purpose |
|--------------------|-----|---------|
| `Lint and types` | `lint-and-types` | `uv sync`, Ruff lint/format, mypy strict, import-linter |
| `Secret scan` | `secret-scan` | gitleaks over repository history |
| `Tests and migrations` | `test` | PostgreSQL 16 service, Alembic upgrade + drift check, full pytest, integration pytest |
| `Docker build` | `docker` | Production-style application image build |

## Recommended GitHub settings

- Require a pull request before merging.
- Require status checks to pass before merging.
- Require branches to be up to date before merging.
- Do not allow bypassing the above settings for administrators during normal product work.
- Restrict pushes to `main` to humans and automation explicitly authorized for release merges.

## Out of scope for required checks

- Live Snowflake, GitHub, or staging connector tests.
- Frontend lint/build (not yet introduced).
- Pre-commit hooks (local developer convenience only).
- Private handoff sync or iCloud transport.

## Verification command parity

Local and Cloud agents can reproduce the CI gate with:

```bash
make ci
gitleaks detect --source . --config .gitleaks.toml --verbose
docker build -t aide:local .
docker compose --env-file .env up --build -d
curl -fsS http://127.0.0.1:${AIDE_HTTP_PORT:-8000}/healthz
```

PostgreSQL integration tests expect `AIDE_TEST_DATABASE_URL` (or the OPS003 localhost default).
