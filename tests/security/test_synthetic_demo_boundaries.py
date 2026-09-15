from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_synthetic_compose_does_not_enable_production_or_staging() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "PRODUCTION" not in compose
    assert "STAGING" not in compose
    assert "SNOWFLAKE_PRIVATE_KEY" not in compose


def test_demo_script_does_not_require_snowflake_names() -> None:
    script = (ROOT / "scripts/synthetic_demo.sh").read_text(encoding="utf-8")
    assert "aide interview demo" in script
    assert "SNOWFLAKE_ACCOUNT" not in script
    assert "kubectl" not in script
    assert "terraform" not in script


def test_dockerfile_and_asgi_keep_production_and_staging_disabled() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    asgi = (ROOT / "asgi.py").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for text in (dockerfile, asgi, example):
        assert "PRODUCTION" not in text
        assert "STAGING" not in text
        assert "SNOWFLAKE_PRIVATE_KEY" not in text


def test_http_demo_docs_require_token_for_remote_use() -> None:
    docs = (ROOT / "docs/ops/SYNTHETIC_CLOUD_DEMO.md").read_text(encoding="utf-8")
    assert "No HTTP token" in docs
    assert "AIDE_SYNTHETIC_DEMO_TOKEN" in docs
    assert "Do not publish a host port" in docs
    assert "AIDE_HTTP_BIND=0.0.0.0" in docs
    assert "fails closed" in docs


def test_independent_verifier_remains_read_only() -> None:
    source = (ROOT / "src/aide/verification/evaluate.py").read_text(encoding="utf-8")
    assert "Read-only Independent Verifier" in source
    assert "execute_mutation" not in source
    assert "CREATE TABLE" not in source
    assert "INSERT INTO" not in source
