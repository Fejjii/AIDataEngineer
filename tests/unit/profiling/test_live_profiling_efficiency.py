"""Live profiling stays under the gateway timeout without weakening evidence."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from aide.capabilities.io import ColumnSpec, DescribeAssetInput, DescribeAssetOutput
from aide.connectors.base.v1_instances import SNOWFLAKE_RO
from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.connectors.snowflake.session import _jsonable
from aide.connectors.snowflake.sql_templates import (
    column_profile_batch_sql,
    column_profile_sql,
    top_values_sql,
)
from aide.domain.sql import AssetKind, AssetRef
from aide.profiling.budgets import (
    LIVE_SNOWFLAKE_PROFILING_BUDGET,
    TINY_OFFLINE_BUDGET,
    ProfilingBudgetExceeded,
    resolve_live_profiling_budget,
)
from aide.profiling.engine import PROFILE_OPERATION_NAMES, profile_selected_assets
from aide.profiling.masking import jsonable

ACCOUNTS = AssetRef(
    connector_id="snowflake_ro",
    address=("VANTARA_RAW", "CRM", "ACCOUNTS"),
    kind=AssetKind.TABLE,
    platform_type="snowflake",
)


def test_offline_budget_stays_at_60_seconds() -> None:
    assert TINY_OFFLINE_BUDGET.max_seconds == 60
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds == 150
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds < 180
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_queries == TINY_OFFLINE_BUDGET.max_queries
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_pairs == TINY_OFFLINE_BUDGET.max_pairs
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.sample_n == TINY_OFFLINE_BUDGET.sample_n


def test_live_budget_must_stay_below_gateway_timeout() -> None:
    selected = resolve_live_profiling_budget(None, gateway_timeout_seconds=180)
    assert selected.max_seconds == 150
    with pytest.raises(ProfilingBudgetExceeded, match="150"):
        resolve_live_profiling_budget(None, gateway_timeout_seconds=150)


def test_decimal_samples_are_json_safe() -> None:
    assert _jsonable(Decimal("10")) == 10
    assert _jsonable(Decimal("10.50")) == 10.5
    assert jsonable(Decimal("10")) == 10
    assert jsonable(Decimal("-1.25")) == -1.25


def test_batched_profile_sql_matches_per_column_aggregates() -> None:
    address = ("VANTARA_RAW", "BILLING", "INVOICES")
    batched = column_profile_batch_sql(address, (("INVOICE_ID", False), ("TOTAL_AMOUNT", True)))
    single_id = column_profile_sql(address, "INVOICE_ID", numeric=False)
    single_amount = column_profile_sql(address, "TOTAL_AMOUNT", numeric=True)
    assert batched.startswith("SELECT ")
    assert batched.count(" FROM ") == 1
    assert 'COUNT(DISTINCT "INVOICE_ID")' in batched
    assert 'COUNT(DISTINCT "TOTAL_AMOUNT")' in batched
    assert 'AVG("TOTAL_AMOUNT")' in batched
    assert "NULL AS C0_MEAN_VALUE" in batched
    assert "AVG" in single_amount
    assert "NULL" in single_id
    assert ";" not in batched


def test_top_values_stay_per_column() -> None:
    sql = top_values_sql(("VANTARA_RAW", "CRM", "ACCOUNTS"), "ACCOUNT_ID", top_k=10)
    assert "UNION" not in sql
    assert "LIMIT 10" in sql
    assert '"ACCOUNT_ID"' in sql


def test_describe_cache_reuses_equivalent_metadata() -> None:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    described = DescribeAssetOutput(
        asset=ACCOUNTS,
        columns=(ColumnSpec(name="ACCOUNT_ID", data_type="VARCHAR", nullable=False, ordinal=1),),
        primary_key=None,
        row_count=None,
        snapshot_id=UUID("6ba7b810-9dad-11d1-80b4-000000000001"),
    )
    connector._describe_cache = {}
    connector._store_describe(described, include_constraints=False, include_row_count=False)
    payload = DescribeAssetInput(asset=ACCOUNTS, include_constraints=False, include_row_count=False)
    assert (
        connector._cached_describe(
            ACCOUNTS.address,
            include_constraints=payload.include_constraints,
            include_row_count=payload.include_row_count,
        )
        == described
    )
    assert (
        connector._cached_describe(
            ACCOUNTS.address, include_constraints=False, include_row_count=True
        )
        is None
    )
    connector._describe_cache = None
    assert (
        connector._cached_describe(
            ACCOUNTS.address, include_constraints=False, include_row_count=False
        )
        is None
    )


@pytest.mark.asyncio
async def test_profile_does_not_repeat_connector_relationship_queries(
    vantara_v2: FakeSnowflakeConnector, selected_assets: tuple[AssetRef, ...]
) -> None:
    calls = 0
    original = vantara_v2.infer_relationships

    async def wrapped(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)  # type: ignore[arg-type]

    vantara_v2.infer_relationships = wrapped  # type: ignore[assignment]
    timings: dict[str, float] = {}
    result = await profile_selected_assets(
        vantara_v2,
        selected_assets,
        fixture_version="v2",
        timings=timings,
    )
    assert calls == 0
    assert result.relationships
    assert result.summary.budget.queries <= TINY_OFFLINE_BUDGET.max_queries
    for name in PROFILE_OPERATION_NAMES:
        assert name in timings
        assert timings[name] >= 0
