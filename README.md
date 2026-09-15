# AI Data Engineer

Enterprise-oriented agentic Data Engineering platform (repository: `AIDataEngineer`).

Product architecture is **ACCEPTED**. DE 002A implements the pure contract kernel and
minimal CI gate (`ruff`, `mypy --strict`, `pytest`, `import-linter`).

Canonical local path: `~/Developer/AIDataEngineer`

Start here: `.ai/MASTER.md`. Interview MVP demo: `docs/INTERVIEW_DEMO.md`.

```bash
uv sync --frozen --all-groups
uv run ruff check .
uv run mypy src tests asgi.py
uv run lint-imports
uv run pytest
uv run aide interview demo
```

Local Docker stack (copy `.env.example` to `.env` first):

```bash
docker compose --env-file .env up --build
curl -fsS http://127.0.0.1:${AIDE_HTTP_PORT:-8000}/healthz
```
