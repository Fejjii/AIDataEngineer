from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _service_block(text: str, name: str) -> str:
    marker = f"  {name}:\n"
    start = text.index(marker)
    rest = text[start + len(marker) :]
    for token in ("\n  postgres:\n", "\n  app:\n", "\nvolumes:\n"):
        end = rest.find(token)
        if end != -1:
            rest = rest[:end]
            break
    return rest


def test_dockerfile_includes_synthetic_fixtures_and_dbt() -> None:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY synthetic ./synthetic" in text
    assert "COPY dbt ./dbt" in text
    assert "chown -R aide:aide /app" in text
    assert "UV_NO_SYNC=1" in text
    assert "SNOWFLAKE_" not in text
    assert "kubectl" not in text
    env_lines = [line for line in text.splitlines() if line.startswith("ENV ")]
    assert len(env_lines) == 1
    assert "AIDE_SYNTHETIC_DEMO_HTTP=0" in text


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


def test_compose_does_not_publish_postgres_host_port() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    postgres = _service_block(text, "postgres")
    assert "ports:" not in postgres
    assert "POSTGRES_PORT" not in text
    assert "5432:5432" not in text
    assert "@postgres:5432/" in text


def test_compose_binds_app_to_localhost_by_default() -> None:
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    app = _service_block(text, "app")
    assert "${AIDE_HTTP_BIND:-127.0.0.1}:${AIDE_HTTP_PORT:-8000}:8000" in app
    assert "${AIDE_SYNTHETIC_DEMO_HTTP:-0}" in app
    assert "${AIDE_SYNTHETIC_DEMO_HTTP:-1}" not in text


def test_entrypoint_migrates_before_exec() -> None:
    text = (ROOT / "scripts/docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "alembic upgrade head" in text
    assert 'exec "$@"' in text


def test_demo_script_has_no_deterministic_postgres_password() -> None:
    script = (ROOT / "scripts/synthetic_demo.sh").read_text(encoding="utf-8")
    assert "aide-demo-pg-" not in script
    assert "synthetic-demo" not in script
    assert "sha256sum" not in script
    assert "POSTGRES_PASSWORD must be set" in script
    assert "AIDE_SYNTHETIC_DEMO_HTTP:-0" in script
    assert "AIDE_SYNTHETIC_DEMO_HTTP:-1" not in script
    assert "secrets.token_urlsafe" in script


def test_ci_smoke_uses_internal_postgres_and_random_password() -> None:
    script = (ROOT / "scripts/ci_compose_smoke.sh").read_text(encoding="utf-8")
    assert "POSTGRES_PORT" not in script
    assert "sha256sum" not in script
    assert "aide-ci-smoke-pg-" not in script
    assert "token_urlsafe" in script
    assert "port postgres 5432" in script
    assert "compose exec" in script or "COMPOSE[@]}" in script
    assert "AIDE_HTTP_BIND:-127.0.0.1" in script
    assert "HTTP demo must be disabled by default" in script


def test_asgi_uses_fail_closed_http_demo_policy() -> None:
    text = (ROOT / "asgi.py").read_text(encoding="utf-8")
    assert "resolve_http_demo" in text
    assert "AIDE_SYNTHETIC_DEMO_TOKEN" in text
    assert "create_production_app" in text


def test_cli_interview_does_not_require_http_token() -> None:
    cli = (ROOT / "src/aide/cli/interview.py").read_text(encoding="utf-8")
    assert "AIDE_SYNTHETIC_DEMO_TOKEN" not in cli
    assert "AIDE_SYNTHETIC_DEMO_HTTP" not in cli


def test_env_example_defaults_are_private() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AIDE_SYNTHETIC_DEMO_HTTP=0" in text
    assert "AIDE_HTTP_BIND=127.0.0.1" in text
    assert "POSTGRES_PORT" not in text
    assert "AIDE_SYNTHETIC_DEMO_HTTP=1" not in text


def test_compose_up_fails_closed_without_postgres_password(tmp_path: Path) -> None:
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    docker.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    env.pop("POSTGRES_PASSWORD", None)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/synthetic_demo.sh"), "up"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "POSTGRES_PASSWORD must be set" in result.stderr
    assert "aide-demo-pg-" not in result.stderr
    assert "change-me" not in result.stderr
    assert result.stdout == ""


def test_demo_http_helper_fails_closed_without_token() -> None:
    env = os.environ.copy()
    env.pop("AIDE_SYNTHETIC_DEMO_TOKEN", None)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/synthetic_demo.sh"), "demo-http"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "AIDE_SYNTHETIC_DEMO_TOKEN is required" in result.stderr
    assert "CLI demo does not need this token" in result.stderr
