"""Typer CLI for the DE 002C offline slice."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import typer
from alembic import command
from alembic.config import Config

from aide.app.runtime import build_offline_stack, session_factory_from_url
from aide.domain.permissions import PermissionLevel

app = typer.Typer(no_args_is_help=True, add_completion=False)
slice_app = typer.Typer(help="Offline DE 002C slice commands")
connectors_app = typer.Typer(help="Connector health commands")
app.add_typer(slice_app, name="slice")
app.add_typer(connectors_app, name="connectors")


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


@slice_app.command("run-offline")
def run_offline(
    requirement: str = typer.Option(
        "Investigate recent order amounts by customer in RAW.SALES",
        "--requirement",
        help="Natural-language investigation request",
    ),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Execute the complete authenticated offline safe-SQL slice."""
    url = _database_url()
    _migrate(url)
    payload = asyncio.run(_run(url, requirement))
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(payload["workflow_id"])


async def _run(url: str, requirement: str) -> dict[str, Any]:
    service = build_offline_stack(session_factory_from_url(url))
    result = await service.run_offline(
        requirement,
        requested_grants=frozenset({PermissionLevel.READ}),
    )
    return {
        "workflow_id": str(result.workflow_id),
        "workflow_state": result.workflow_state,
        "parked": result.parked,
        "park_reason": result.park_reason,
        "effective_grants": sorted(item.value for item in result.grants.effective),
        "catalogue_assets": [
            list(item.address) for item in (result.catalogue.assets if result.catalogue else ())
        ],
        "selected": [
            list(item.asset.address)
            for item in (result.selection.selected if result.selection else ())
        ],
        "sql": result.generated_sql.sql.text if result.generated_sql else None,
        "query_tag": result.query_tag,
        "validation_passed": result.validation.passed if result.validation else False,
        "summary_outcome": result.summary.outcome if result.summary else None,
        "row_count": result.execution.row_count if result.execution else 0,
        "provenance_mode": result.provenance.execution_mode.value if result.provenance else None,
    }


@connectors_app.command("check")
def connectors_check(
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Report fake and real Snowflake health. Prints env var names, never secret values."""
    payload = asyncio.run(_connector_health())
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    for item in payload:
        reasons = ",".join(item["reason_codes"]) if item["reason_codes"] else "-"
        typer.echo(f"{item['connector_id']} fake={item['is_fake']} {item['status']} {reasons}")


async def _connector_health() -> list[dict[str, Any]]:
    from aide.connectors.snowflake.fake import build_fake_pair
    from aide.connectors.snowflake.real import build_real_pair

    reports: list[dict[str, Any]] = []
    fake_ro, fake_dev = build_fake_pair()
    real_ro, real_dev = build_real_pair()
    for connector in (fake_ro, fake_dev, real_ro, real_dev):
        snapshot = await connector.health()
        reports.append(
            {
                "connector_id": snapshot.connector_id,
                "identity_class": connector.spec.identity_class.value,
                "is_fake": connector.spec.is_fake,
                "status": snapshot.status,
                "reason_codes": list(snapshot.reason_codes),
            }
        )
        await connector.close()
    return reports


def main() -> None:
    app()


if __name__ == "__main__":
    main()
