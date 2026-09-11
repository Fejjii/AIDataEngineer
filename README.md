# AI Data Engineer

Enterprise-oriented agentic Data Engineering platform (repository: `AIDataEngineer`).

Product architecture is **ACCEPTED**. DE 002A implements the pure contract kernel and
minimal CI gate (`ruff`, `mypy --strict`, `pytest`, `import-linter`).

Canonical local path: `~/Developer/AIDataEngineer`

Start here: `.ai/MASTER.md`

```bash
uv sync --frozen --all-groups
uv run ruff check .
uv run mypy src tests
uv run lint-imports
uv run pytest
```
