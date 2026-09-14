"""Load Vantara CSV fixtures into Snowflake using the DEV service identity.

This is bootstrap I/O, not the product DEV connector. Product policy still forbids
VANTARA_RAW writes through `snowflake_dev`. Never log credential values.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from aide.connectors.base.spec import IdentityClass
from aide.connectors.snowflake.config import (
    ROLE_DEVELOPMENT,
    EnvConnectorSecretResolver,
    settings_for_identity,
)
from aide.connectors.snowflake.errors import sanitize_error_message
from aide.connectors.snowflake.session import connect_kwargs, private_key_der
from synthetic.vantara.export.snowflake_export import (
    COPY_FILE_FORMAT,
    SCHEMAS,
    columns_for_v2,
    csv_relative_path,
    snowflake_type,
    table_stage,
)
from synthetic.vantara.schema import SNOWFLAKE_DATABASE, TABLES

try:
    import snowflake.connector
except ImportError:  # pragma: no cover
    snowflake = None  # type: ignore[assignment]


def csv_data_row_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return max(sum(1 for _ in handle) - 1, 0)


def _result_status(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("status") or row.get("STATUS") or "")
    if isinstance(row, (tuple, list)) and len(row) > 1:
        return str(row[1] or "")
    return ""


def expected_v2_row_counts(csv_root: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table_def in TABLES.values():
        rel = csv_relative_path(table_def.schema, table_def.name)
        counts[f"{table_def.schema}.{table_def.name}"] = csv_data_row_count(csv_root / rel)
    return counts


def _dev_connect() -> Any:
    if snowflake is None:
        raise RuntimeError("snowflake-connector-python is not installed")
    settings = settings_for_identity(IdentityClass.DEVELOPMENT)
    resolver = EnvConnectorSecretResolver()
    account = resolver.resolve(settings.account)
    user = resolver.resolve(settings.user)
    private_key = resolver.resolve(settings.private_key)
    warehouse = resolver.resolve(settings.warehouse)
    passphrase: SecretStr | None = None
    if settings.passphrase is not None:
        passphrase = resolver.resolve(settings.passphrase)
    key = private_key_der(private_key, passphrase)
    return snowflake.connector.connect(
        **connect_kwargs(
            account=account.get_secret_value(),
            user=user.get_secret_value(),
            private_key=key,
            warehouse=warehouse.get_secret_value(),
            role=ROLE_DEVELOPMENT,
            database=SNOWFLAKE_DATABASE,
            query_tag="aide:v1;bootstrap=vantara_tiny_v2",
            timeout_seconds=120,
        )
    )


def load_v2_csv(*, profile: str, fixture_root: Path) -> dict[str, int]:
    """Create VANTARA_RAW schemas/tables and COPY tiny/demo/full v2 CSVs.

    Uses the DEV Snowflake user/key directly. Does not call RealSnowflakeConnector.
    """
    csv_root = fixture_root / "v2" / "csv"
    if not csv_root.is_dir():
        raise FileNotFoundError(f"missing v2 csv directory under {fixture_root}")
    expected = expected_v2_row_counts(csv_root)
    connection = _dev_connect()
    loaded: dict[str, int] = {}
    try:
        cursor = connection.cursor()
        try:
            with suppress(Exception):
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS {SNOWFLAKE_DATABASE}")
            cursor.execute(f"USE DATABASE {SNOWFLAKE_DATABASE}")
            for schema in SCHEMAS:
                # Schemas already exist. CREATE SCHEMA is optional and not granted
                # to the bootstrap CREATE TABLE grant on VANTARA_RAW.
                with suppress(Exception):
                    cursor.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            for table_key, table_def in TABLES.items():
                columns = columns_for_v2(table_key, table_def.columns)
                col_sql = ", ".join(
                    f"{col.name} {snowflake_type(col.duckdb_type)}" for col in columns
                )
                qualified = f"{table_def.schema}.{table_def.name}"
                stage = table_stage(table_def.schema, table_def.name)
                csv_path = (
                    csv_root / csv_relative_path(table_def.schema, table_def.name)
                ).resolve()
                if not csv_path.is_file():
                    raise FileNotFoundError(f"missing CSV for {qualified}")
                uri = csv_path.as_uri()
                cursor.execute(f"CREATE OR REPLACE TABLE {qualified} ({col_sql})")
                cursor.execute(f"PUT '{uri}' {stage} AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
                cursor.execute(
                    f"COPY INTO {qualified} FROM {stage} "
                    f"FILE_FORMAT=({COPY_FILE_FORMAT}) ON_ERROR='ABORT_STATEMENT'"
                )
                copy_rows = cursor.fetchall() or ()
                failed = [
                    _result_status(row)
                    for row in copy_rows
                    if _result_status(row).upper() not in {"", "LOADED"}
                ]
                if failed:
                    raise RuntimeError(f"COPY did not load {qualified}: {failed}")
                cursor.execute(f"SELECT COUNT(*) AS N FROM {qualified}")
                row = cursor.fetchone()
                count = int(row[0]) if row is not None else 0
                loaded[qualified] = count
        except Exception as exc:
            raise RuntimeError(sanitize_error_message(str(exc))) from exc
        finally:
            cursor.close()
    finally:
        connection.close()
    mismatched = {
        name: (loaded[name], expected[name])
        for name in expected
        if loaded.get(name) != expected[name]
    }
    if mismatched:
        raise RuntimeError(f"row count mismatch after load: {mismatched}")
    return loaded
