.PHONY: sync lint format typecheck imports test integration alembic-upgrade alembic-check ci docker-build compose-up compose-down verify

sync:
	uv sync --frozen --all-groups

lint:
	uv run ruff check .

format:
	uv run ruff format --check .

typecheck:
	uv run mypy src tests asgi.py

imports:
	uv run lint-imports

test:
	uv run pytest

integration:
	uv run pytest tests/integration

alembic-upgrade:
	uv run alembic upgrade head

alembic-check:
	uv run alembic check

ci: sync lint format typecheck imports alembic-upgrade alembic-check test integration

docker-build:
	docker build -t aide:local .

compose-up:
	docker compose up --build -d

compose-down:
	docker compose down -v

verify:
	./scripts/verify_environment.sh --verify
