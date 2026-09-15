"""Interview MVP demo, benchmark, and credential-gated live smoke commands."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import typer
from alembic import command
from alembic.config import Config

from aide.app.runtime import session_factory_from_url
from aide.domain.benchmark import LiveSmokeStatus

interview_app = typer.Typer(help="Interview MVP demo and benchmark commands")


def _database_url() -> str:
    return os.environ.get(
        "AIDE_DATABASE_URL",
        os.environ.get(
            "AIDE_TEST_DATABASE_URL", "postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev"
        ),
    )


def _migrate(url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@interview_app.command("demo")
def interview_demo(
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Run the offline Interview MVP twice and print a recruiter-ready report."""
    url = _database_url()
    _migrate(url)
    payload = asyncio.run(_run_demo(url))
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(payload["report"])
    if payload["benchmark_verdict"] != "PASS":
        raise typer.Exit(1)


@interview_app.command("benchmark")
def interview_benchmark(
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Run the offline Interview MVP twice and assert deterministic equivalence."""
    url = _database_url()
    _migrate(url)
    payload = asyncio.run(_run_demo(url))
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(payload["report"])
        typer.echo("")
        typer.echo(payload["scorecard"])
    if payload["benchmark_verdict"] != "PASS":
        raise typer.Exit(1)


@interview_app.command("live-smoke")
def interview_live_smoke(
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Credential-gated grant metadata probe plus governed live Interview path."""
    payload = asyncio.run(_run_live())
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(f"status={payload['status']}")
        typer.echo(payload["detail"])
        if payload["missing_env_names"]:
            typer.echo("missing_env_names=" + ",".join(payload["missing_env_names"]))
            typer.echo(payload["human_action"])
    status = payload["status"]
    if status == LiveSmokeStatus.CREDENTIAL_GATED.value:
        raise typer.Exit(2)
    if status != LiveSmokeStatus.PASSED.value:
        raise typer.Exit(1)


async def _run_demo(url: str) -> dict[str, Any]:
    from aide.app.benchmarking.demo import render_demo_report, render_scorecard
    from aide.app.benchmarking.runner import run_offline_benchmark
    from aide.connectors.snowflake.live_probe import (
        HUMAN_ACTION,
        missing_live_secret_names,
    )
    from aide.domain.benchmark import INTERVIEW_REQUEST

    work_root = Path(tempfile.mkdtemp(prefix="aide-interview-"))
    factory = session_factory_from_url(url)
    missing = missing_live_secret_names()
    live_status = LiveSmokeStatus.CREDENTIAL_GATED if missing else LiveSmokeStatus.NOT_RUN
    live_detail = HUMAN_ACTION if missing else ""
    report, first, _second = await run_offline_benchmark(
        factory,
        work_root,
        requirement=INTERVIEW_REQUEST,
        live_smoke=live_status,
        live_smoke_detail=live_detail,
    )
    return {
        "report": render_demo_report(first, report),
        "scorecard": render_scorecard(report),
        "benchmark_verdict": report.verdict.value,
        "determinism": report.determinism.equivalent,
        "evidence_completeness_pct": report.evidence_completeness.completeness_pct,
        "verifier": report.verifier_verdict.value if report.verifier_verdict else None,
        "live_smoke": report.live_smoke.value,
        "scenario_id": report.scenario_id,
        "workflow_ids": [str(item.workflow_id) for item in report.runs],
    }


async def _run_live() -> dict[str, Any]:
    from aide.app.interview import run_credentialed_live_interview_smoke
    from aide.connectors.snowflake.live_probe import missing_live_secret_names

    if missing_live_secret_names():
        report = await run_credentialed_live_interview_smoke()
        return report.model_dump(mode="json")
    url = _database_url()
    _migrate(url)
    work_root = Path(tempfile.mkdtemp(prefix="aide-interview-live-"))
    factory = session_factory_from_url(url)
    report = await run_credentialed_live_interview_smoke(factory, work_root=work_root)
    return report.model_dump(mode="json")


__all__ = ["interview_app"]
