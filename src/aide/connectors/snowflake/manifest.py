"""Pinned Vantara tiny-fixture dual-load helpers for the interview DEV namespace.

Loads local CSV files into workflow-scoped AIDE_DEV objects. Never SELECTs
from VANTARA_RAW. `snowflake_ro` remains the only product identity that reads RAW.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID

from synthetic.vantara.config import PACKAGE_ROOT

from aide.capabilities.io import LoadedSourceTable
from aide.connectors.snowflake.namespace import (
    DEV_DATABASE,
    require_dev_namespace,
    workflow_short_id,
)
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef

TINY_MANIFEST_PATH = PACKAGE_ROOT / "fixtures" / "tiny" / "manifest.json"
_UNSAFE_RAW = "VANTARA_RAW"


def tiny_manifest_digest() -> str:
    return hashlib.sha256(TINY_MANIFEST_PATH.read_bytes()).hexdigest()


def verify_pinned_manifest(expected_sha256: str) -> str:
    digest = tiny_manifest_digest()
    if digest != expected_sha256.lower():
        raise ValueError("pinned Vantara tiny manifest digest does not match")
    return digest


def csv_path_for(address: tuple[str, str, str], version: str) -> Path:
    return (
        PACKAGE_ROOT
        / "fixtures"
        / "tiny"
        / version
        / "csv"
        / address[1].lower()
        / (f"{address[2].lower()}.csv")
    )


def workflow_source_address(
    workflow_id: UUID, source: tuple[str, str, str]
) -> tuple[str, str, str]:
    _database, schema, table = source
    return (DEV_DATABASE, f"{workflow_short_id(workflow_id)}_{schema}", table)


def flattened_ident(address: tuple[str, ...]) -> str:
    return ".".join(part.upper() for part in address)


def schema_sha256(columns: tuple[str, ...]) -> str:
    payload = ",".join(columns).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_csvs_into_dev(
    conn: Any,
    *,
    workflow_id: UUID,
    version: str,
    selected: tuple[tuple[str, str, str], ...],
    flattened: bool,
) -> tuple[LoadedSourceTable, ...]:
    """Copy pinned CSVs into workflow DEV schemas. Never queries VANTARA_RAW."""
    if version not in {"v1", "v2"}:
        raise ValueError("fixture version must be v1 or v2")
    loaded: list[LoadedSourceTable] = []
    for source in selected:
        if source[0].upper() == _UNSAFE_RAW:
            # Fixture identity only; the file is local. Reject any SQL against RAW.
            pass
        target = workflow_source_address(workflow_id, source)
        require_dev_namespace(
            AssetRef(
                connector_id="snowflake_dev",
                address=target,
                kind=AssetKind.TABLE,
                platform_type="snowflake",
            ),
            workflow_id,
        )
        csv_file = csv_path_for(source, version)
        if not csv_file.is_file():
            raise FileNotFoundError(f"pinned fixture CSV missing: {csv_file}")
        header = csv_file.read_text(encoding="utf-8").splitlines()[0]
        columns = tuple(part.strip() for part in header.split(","))
        if flattened:
            ident = flattened_ident(target)
            conn.execute(f'DROP TABLE IF EXISTS "{ident}"')
            conn.execute(
                f'CREATE TABLE "{ident}" AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)',
                [str(csv_file.resolve())],
            )
            count_row = conn.execute(f'SELECT COUNT(*) FROM "{ident}"').fetchone()
        else:
            schema = target[1]
            table = target[2]
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            conn.execute(f'DROP TABLE IF EXISTS "{schema}"."{table}"')
            conn.execute(
                f'CREATE TABLE "{schema}"."{table}" AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)',
                [str(csv_file.resolve())],
            )
            count_row = conn.execute(f'SELECT COUNT(*) FROM "{schema}"."{table}"').fetchone()
        row_count = int(count_row[0]) if count_row is not None else 0
        loaded.append(
            LoadedSourceTable(
                address=target,
                schema_name=target[1],
                row_count=row_count,
                schema_sha256=schema_sha256(columns),
            )
        )
    return tuple(loaded)


def reject_raw_sql(sql: str) -> None:
    if _UNSAFE_RAW in sql.upper():
        from aide.connectors.snowflake.errors import SnowflakeMappedError

        raise SnowflakeMappedError(
            FailureClass.UNSAFE_OPERATION,
            "DEV load must not read or write VANTARA_RAW",
        )
