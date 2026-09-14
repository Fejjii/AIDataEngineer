from __future__ import annotations

from collections.abc import Iterator

import pytest

from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.domain.sql import AssetRef
from aide.profiling.fixtures import demo_selected_assets
from aide.profiling.offline import open_offline_vantara


@pytest.fixture
def vantara_v1() -> Iterator[FakeSnowflakeConnector]:
    connector = open_offline_vantara("v1")
    try:
        yield connector
    finally:
        connector._conn.close()


@pytest.fixture
def vantara_v2() -> Iterator[FakeSnowflakeConnector]:
    connector = open_offline_vantara("v2")
    try:
        yield connector
    finally:
        connector._conn.close()


@pytest.fixture
def selected_assets() -> tuple[AssetRef, ...]:
    return demo_selected_assets()
