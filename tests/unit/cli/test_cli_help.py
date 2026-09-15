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


def test_connectors_check_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["connectors", "check", "--help"])
    assert result.exit_code == 0
    assert "health" in result.stdout.lower() or "json" in result.stdout.lower()


def test_interview_demo_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["interview", "demo", "--help"])
    assert result.exit_code == 0
    assert "offline" in result.stdout.lower() or "interview" in result.stdout.lower()


def test_interview_benchmark_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["interview", "benchmark", "--help"])
    assert result.exit_code == 0
    assert "twice" in result.stdout.lower() or "deterministic" in result.stdout.lower()


def test_interview_live_smoke_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["interview", "live-smoke", "--help"])
    assert result.exit_code == 0
    assert "credential" in result.stdout.lower() or "live" in result.stdout.lower()


def test_demo_load_snowflake_command_is_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["demo", "load-snowflake", "--help"])
    assert result.exit_code == 0
    assert "profile" in result.stdout.lower()
