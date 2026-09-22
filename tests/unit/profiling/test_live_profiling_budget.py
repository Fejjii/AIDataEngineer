"""Offline profiling stays on the 60s budget; real Snowflake uses the live budget."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

import pytest
from tests.connectors.contract.conftest import make_context

from aide.app.interview import live_snowflake_read_connector
from aide.app.supervisor import _profiling_templates
from aide.capabilities.io import ProfileEstateInput
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.v1_instances import SNOWFLAKE_RO
from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_RO
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef
from aide.profiling.budgets import (
    LIVE_SNOWFLAKE_PROFILING_BUDGET,
    TINY_OFFLINE_BUDGET,
    BudgetTracker,
    ProfilingBudget,
    ProfilingBudgetExceeded,
    resolve_live_profiling_budget,
)
from aide.profiling.engine import ProfilingEngine, profile_selected_assets

ORDERS = AssetRef(
    connector_id="snowflake_ro",
    address=("RAW", "SALES", "ORDERS"),
    kind=AssetKind.TABLE,
    platform_type="snowflake",
)


def test_offline_budget_remains_60_seconds() -> None:
    assert TINY_OFFLINE_BUDGET.max_seconds == 60
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds == 150
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds > TINY_OFFLINE_BUDGET.max_seconds
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_rows == TINY_OFFLINE_BUDGET.max_rows
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_bytes == TINY_OFFLINE_BUDGET.max_bytes
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_queries == TINY_OFFLINE_BUDGET.max_queries
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_pairs == TINY_OFFLINE_BUDGET.max_pairs
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.sample_n == TINY_OFFLINE_BUDGET.sample_n


def test_gateway_timeout_stays_above_the_live_profiler_budget() -> None:
    gateway_timeout = kernel_registry().get("profile_estate", 1).timeout_seconds
    assert gateway_timeout == 180
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds < gateway_timeout
    assert TINY_OFFLINE_BUDGET.max_seconds < gateway_timeout
    template = _profiling_templates((ORDERS,), "v1")[0]
    assert template.capability_id == "profile_estate"
    assert template.timeout_seconds == gateway_timeout
    assert LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds < template.timeout_seconds
    selected = resolve_live_profiling_budget(None, gateway_timeout_seconds=gateway_timeout)
    assert selected is LIVE_SNOWFLAKE_PROFILING_BUDGET
    with pytest.raises(ProfilingBudgetExceeded):
        resolve_live_profiling_budget(
            replace(LIVE_SNOWFLAKE_PROFILING_BUDGET, max_seconds=gateway_timeout),
            gateway_timeout_seconds=gateway_timeout,
        )


def test_time_budget_exhaustion_fails_closed() -> None:
    for budget in (TINY_OFFLINE_BUDGET, LIVE_SNOWFLAKE_PROFILING_BUDGET):
        tracker = BudgetTracker(budget)
        tracker.started = perf_counter() - (budget.max_seconds + 1)
        with pytest.raises(ProfilingBudgetExceeded) as caught:
            tracker.charge_query()
        assert caught.value.failure_class is FailureClass.RESOURCE_LIMIT


@pytest.mark.asyncio
async def test_offline_engine_uses_the_60_second_budget() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    engine = ProfilingEngine(connector, fixture_version="catalogue")
    assert engine._budget is TINY_OFFLINE_BUDGET
    result = await profile_selected_assets(connector, (ORDERS,), fixture_version="catalogue")
    assert result.summary.budget.max_seconds == 60
    output = await connector.profile_estate(
        ProfileEstateInput(assets=(ORDERS,), fixture_version="v1"),
        make_context(),
    )
    assert output.run_payload["summary"]["budget"]["max_seconds"] == 60
    await connector.close()


@pytest.mark.asyncio
async def test_engine_time_budget_exhaustion_fails_closed() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    engine = ProfilingEngine(
        connector, fixture_version="catalogue", budget=LIVE_SNOWFLAKE_PROFILING_BUDGET
    )
    engine._tracker.started = perf_counter() - (LIVE_SNOWFLAKE_PROFILING_BUDGET.max_seconds + 1)
    with pytest.raises(ProfilingBudgetExceeded) as caught:
        await engine.run((ORDERS,))
    assert caught.value.failure_class is FailureClass.RESOURCE_LIMIT
    await connector.close()


def test_real_snowflake_connector_defaults_to_the_live_budget() -> None:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    assert connector.profiling_budget is LIVE_SNOWFLAKE_PROFILING_BUDGET
    assert (
        connector.profiling_budget.max_seconds
        < kernel_registry().get("profile_estate", 1).timeout_seconds
    )
    with pytest.raises(ProfilingBudgetExceeded):
        RealSnowflakeConnector(
            SNOWFLAKE_RO,
            profiling_budget=replace(LIVE_SNOWFLAKE_PROFILING_BUDGET, max_seconds=180),
        )


def test_live_read_connector_is_explicit_configuration() -> None:
    configured = live_snowflake_read_connector()
    assert configured.profiling_budget is LIVE_SNOWFLAKE_PROFILING_BUDGET
    custom = RealSnowflakeConnector(
        SNOWFLAKE_RO,
        profiling_budget=replace(TINY_OFFLINE_BUDGET, max_seconds=90),
    )
    assert live_snowflake_read_connector(custom) is custom
    assert custom.profiling_budget.max_seconds == 90


def test_offline_engine_keeps_its_120_second_deadline() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    engine = ProfilingEngine(connector, fixture_version="catalogue")
    remaining = (engine._context.deadline - datetime.now(UTC)).total_seconds()
    assert 119 <= remaining <= 120


@pytest.mark.asyncio
async def test_gateway_deadline_is_enforced_above_the_live_budget() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    expired = make_context(deadline_seconds=-1)
    engine = ProfilingEngine(
        connector,
        fixture_version="catalogue",
        budget=LIVE_SNOWFLAKE_PROFILING_BUDGET,
        context=expired,
    )
    with pytest.raises(SnowflakeMappedError) as caught:
        await engine.run((ORDERS,))
    assert caught.value.failure is FailureClass.TIMEOUT
    await connector.close()


@pytest.mark.asyncio
async def test_real_profile_estate_passes_the_live_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class _Run:
        fixture_version = "v1"
        duration_seconds = 1.0
        profiles: tuple[object, ...] = ()
        relationships: tuple[object, ...] = ()
        relationships_id = uuid4()

        def model_dump(self, mode: str = "json") -> dict[str, object]:
            del mode
            return {}

    async def _capture(warehouse: object, selected: object, **kwargs: object) -> _Run:
        del warehouse, selected
        budget = kwargs.get("budget")
        assert isinstance(budget, ProfilingBudget)
        captured["budget"] = budget
        captured["context"] = kwargs.get("context")
        return _Run()

    monkeypatch.setattr("aide.profiling.engine.profile_selected_assets", _capture)
    connector = live_snowflake_read_connector()
    monkeypatch.setattr(connector, "_require_credentials", lambda: None)
    gateway_context = make_context(deadline_seconds=180)
    await connector.profile_estate(
        ProfileEstateInput(assets=(ORDERS,), fixture_version="v1"),
        gateway_context,
    )
    assert captured["budget"] is LIVE_SNOWFLAKE_PROFILING_BUDGET
    budget = captured["budget"]
    assert isinstance(budget, ProfilingBudget)
    assert budget.max_seconds < 180
    assert captured["context"] is gateway_context
