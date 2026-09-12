"""Demo fixture commands for Vantara synthetic data."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from synthetic.vantara.build import build_fixtures
from synthetic.vantara.config import DEFAULT_SEED, Profile

demo_app = typer.Typer(help="Vantara demo fixture commands")


@demo_app.command("build-fixtures")
def build_fixtures_command(
    profile: Profile = typer.Option(  # noqa: B008
        ..., "--profile", help="Scale profile: tiny, demo, or full"
    ),
    seed: int = typer.Option(  # noqa: B008
        DEFAULT_SEED, "--seed", help="Deterministic generation seed"
    ),
    output_root: Path | None = typer.Option(  # noqa: B008
        None,
        "--output-root",
        help="Override fixture output directory",
    ),
    json_output: bool = typer.Option(True, "--json/--no-json"),  # noqa: B008
) -> None:
    """Build deterministic Vantara fixtures for the selected profile."""
    result = build_fixtures(profile, seed=seed, output_root=output_root)
    payload = {
        "profile": result.profile,
        "seed": result.seed,
        "total_rows": result.total_rows,
        "build_seconds": round(result.build_seconds, 3),
        "duckdb_hashes": result.duckdb_hashes,
        "expected_dir": str(result.expected_dir),
        "output_root": str(result.output_root),
    }
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(
            f"Built {result.profile} fixtures: {result.total_rows} rows in "
            f"{result.build_seconds:.2f}s"
        )
