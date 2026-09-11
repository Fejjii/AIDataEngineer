# DE-ADR-025 — Python 3.12, uv, ruff, mypy strict, pytest

- **Date:** 2026-09-11 · **Status:** ACCEPTED · **Task:** DE 001

## Context
Reproducibility across LOCAL, Cloud and CI was a recurring gap in previous projects
(mixed pip/venv/uv, unpinned versions). dbt adapters and the Snowflake connector lag the
newest Python releases.

## Decision
Python 3.12 pinned (`.python-version`, `pyproject.toml`, CI) — re-verified against
`dbt-snowflake` and `snowflake-connector-python` at DE 002; `uv` with committed `uv.lock`
and `uv run` for every command; `ruff` for lint and format; `mypy --strict`;
`import-linter` for boundaries; `pytest` + `pytest-asyncio` + `hypothesis` +
`testcontainers`; `gitleaks` in pre-commit and CI; Node LTS + pnpm pinned for the frontend.

## Alternatives
- Poetry/pip-tools: rejected — slower, second lock format.
- Latest Python: rejected until adapters support it.
- black + isort + flake8: rejected — ruff covers all.

## Consequences
- `scripts/verify-environment.sh` checks versions and required env var *names* for LOCAL and Cloud parity.
- Upgrading Python is an explicit task with adapter compatibility checks.
