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
