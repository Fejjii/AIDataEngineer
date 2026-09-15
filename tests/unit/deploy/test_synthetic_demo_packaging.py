from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_dockerfile_includes_synthetic_fixtures_and_dbt() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY synthetic ./synthetic" in text
    assert "COPY dbt ./dbt" in text
    assert "SNOWFLAKE_" not in text
    assert "kubectl" not in text


def test_compose_is_one_app_and_postgres() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "postgres:" in text
    assert "image: postgres:16" in text
    assert "AIDE_SYNTHETIC_DEMO_HTTP" in text
    assert "SNOWFLAKE_" not in text
    assert "redis" not in text
    assert "kafka" not in text
    assert "temporal" not in text
    services = [line for line in text.splitlines() if line.startswith("  ") and line.endswith(":")]
    assert "  postgres:" in services
    assert "  app:" in services


def test_entrypoint_migrates_before_exec() -> None:
    text = (ROOT / "scripts/docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in text
    assert 'exec "$@"' in text
