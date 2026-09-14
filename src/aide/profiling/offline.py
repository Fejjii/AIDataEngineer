"""Offline Vantara fixture binding for the accepted FakeSnowflakeConnector."""

from __future__ import annotations

from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_RO
from aide.profiling.fixtures import install_vantara_tables


def bind_vantara_fixtures(connector: FakeSnowflakeConnector, *, version: str) -> None:
    conn = getattr(connector, "_conn", None)
    if conn is None:
        raise TypeError("offline fixture binding requires a DuckDB-backed warehouse")
    install_vantara_tables(conn, version)


def open_offline_vantara(version: str) -> FakeSnowflakeConnector:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    bind_vantara_fixtures(connector, version=version)
    return connector
