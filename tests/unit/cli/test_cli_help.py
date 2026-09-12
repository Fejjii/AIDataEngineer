from __future__ import annotations

from typer.testing import CliRunner

from aide.cli.main import app


def test_offline_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["slice", "run-offline", "--help"])
    assert result.exit_code == 0
    assert "offline" in result.stdout.lower() or "requirement" in result.stdout.lower()


def test_demo_build_fixtures_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "build-fixtures", "--help"])
    assert result.exit_code == 0
    assert "profile" in result.stdout.lower()
