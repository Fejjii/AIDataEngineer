from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aide.capabilities.io import ProfileDatasetInput, SampleDatasetInput
from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_RO
from aide.domain.sql import AssetKind, AssetRef
from aide.orchestration.materialization import TemplateSpec
from aide.orchestration.phases.profiling import (
    PROFILING_EXIT_CRITERIA,
    allocate_profiling_slots,
    build_profiling_plan,
    build_profiling_templates,
    infer_local_id,
)
from aide.profiling.artifacts import ProfilingRunResult
from aide.profiling.budgets import ProfilingBudget, ProfilingBudgetExceeded
from aide.profiling.engine import ProfilingEngine, profile_selected_assets, sample_assets_for
from aide.profiling.fixtures import (
    DEMO_SELECTED_ADDRESSES,
    EXCLUDED_DEMO_ADDRESSES,
    SAMPLE_PRIORITY_ADDRESSES,
)

ORDERS = AssetRef(
    connector_id="snowflake_ro",
    address=("RAW", "SALES", "ORDERS"),
    kind=AssetKind.TABLE,
    platform_type="snowflake",
)


def _budget(*, max_queries: int = 400, sample_n: int = 20) -> ProfilingBudget:
    return ProfilingBudget(
        max_rows=10_000,
        max_bytes=1_000_000,
        max_seconds=60,
        max_queries=max_queries,
        max_pairs=80,
        sample_n=sample_n,
        sample_asset_limit=3,
        top_k=5,
    )


@pytest.mark.asyncio
async def test_engine_uses_existing_profile_dataset_capability() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    engine = ProfilingEngine(connector, fixture_version="catalogue", budget=_budget())
    result = await engine.run((ORDERS,))
    profile = result.profiles[0]
    assert profile.row_count == 3
    assert any(key.columns == ("ORDER_ID",) for key in profile.candidate_keys)
    assert all(0 <= column.null_ratio <= 1 for column in profile.columns)
    assert result.summary.excluded_addresses == ()
    await connector.close()


@pytest.mark.asyncio
async def test_excluded_addresses_only_when_supplied() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    supplied = (("RAW", "CRM", "ACCOUNTS"),)
    engine = ProfilingEngine(
        connector,
        fixture_version="catalogue",
        budget=_budget(),
        excluded_addresses=supplied,
    )
    result = await engine.run((ORDERS,))
    assert result.summary.excluded_addresses == supplied
    await connector.close()


@pytest.mark.asyncio
async def test_sample_n_above_20_is_rejected() -> None:
    with pytest.raises(ProfilingBudgetExceeded):
        ProfilingBudget(
            max_rows=10,
            max_bytes=1000,
            max_seconds=5,
            max_queries=10,
            max_pairs=2,
            sample_n=21,
            sample_asset_limit=1,
            top_k=3,
        )
    with pytest.raises(ValidationError):
        SampleDatasetInput(asset=ORDERS, n=21)


@pytest.mark.asyncio
async def test_budget_enforcement_stops_before_full_scan() -> None:
    connector = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    engine = ProfilingEngine(connector, fixture_version="catalogue", budget=_budget(max_queries=1))
    with pytest.raises(ProfilingBudgetExceeded):
        await engine.run((ORDERS,))
    await connector.close()


@pytest.mark.asyncio
async def test_profiling_determinism_on_tiny_v2(
    vantara_v2: FakeSnowflakeConnector, selected_assets: tuple[AssetRef, ...]
) -> None:
    first = await profile_selected_assets(
        vantara_v2,
        selected_assets,
        fixture_version="v2",
        sample_priority=SAMPLE_PRIORITY_ADDRESSES,
    )
    second = await profile_selected_assets(
        vantara_v2,
        selected_assets,
        fixture_version="v2",
        sample_priority=SAMPLE_PRIORITY_ADDRESSES,
    )
    assert [item.profile_id for item in first.profiles] == [
        item.profile_id for item in second.profiles
    ]
    assert first.relationships_id == second.relationships_id
    assert first.summary.facts == second.summary.facts
    left = [
        (
            item.candidate.from_asset.address,
            item.candidate.from_columns,
            item.candidate.inclusion_ratio,
        )
        for item in first.relationships
        if item.measured
    ]
    right = [
        (
            item.candidate.from_asset.address,
            item.candidate.from_columns,
            item.candidate.inclusion_ratio,
        )
        for item in second.relationships
        if item.measured
    ]
    assert left == right


@pytest.mark.asyncio
async def test_artifact_serialization_round_trip(
    vantara_v1: FakeSnowflakeConnector, selected_assets: tuple[AssetRef, ...]
) -> None:
    result = await profile_selected_assets(
        vantara_v1,
        selected_assets,
        fixture_version="v1",
        budget=_budget(),
        sample_priority=SAMPLE_PRIORITY_ADDRESSES,
    )
    payload = result.model_dump(mode="json")
    restored = ProfilingRunResult.model_validate(payload)
    assert restored.summary.facts == result.summary.facts
    encoded = result.model_dump_json()
    json.loads(encoded)
    assert "@" not in encoded or "***@" in encoded


def test_deterministic_task_ordering(selected_assets: tuple[AssetRef, ...]) -> None:
    templates = build_profiling_templates(selected_assets)
    local_ids = [item.local_id for item in templates]
    assert local_ids == sorted(local_ids)
    infer = infer_local_id()
    assert infer in local_ids
    profile_ids = [item.local_id for item in templates if item.capability_id == "profile_dataset"]
    sample_ids = [item.local_id for item in templates if item.capability_id == "sample_dataset"]
    assert all(item < infer for item in profile_ids)
    assert all(item > infer for item in sample_ids)
    infer_template = next(item for item in templates if item.local_id == infer)
    assert set(infer_template.depends_on) == set(profile_ids)
    plan = build_profiling_plan(selected_assets)
    assert plan.phase.value == "PROFILING"
    assert plan.phase_exit_criteria == PROFILING_EXIT_CRITERIA
    profiled = set()
    for item in templates:
        if item.capability_id != "profile_dataset":
            continue
        asset_payload = item.unresolved_inputs["asset"]
        assert isinstance(asset_payload, dict)
        address = asset_payload["address"]
        assert isinstance(address, list)
        profiled.add(tuple(address))
    assert set(DEMO_SELECTED_ADDRESSES) == profiled
    assert not any(address in profiled for address in EXCLUDED_DEMO_ADDRESSES)


def test_task_limit_does_not_profile_unselected_assets(
    selected_assets: tuple[AssetRef, ...],
) -> None:
    templates = build_profiling_templates(selected_assets, max_tasks=6)
    assert len(templates) <= 6
    capabilities = {item.capability_id for item in templates}
    assert "infer_relationships" in capabilities
    profile_count = sum(1 for item in templates if item.capability_id == "profile_dataset")
    assert 1 <= profile_count < len(selected_assets)


def _task_counts(templates: tuple[TemplateSpec, ...]) -> tuple[int, int, int, int]:
    profiles = sum(1 for item in templates if item.capability_id == "profile_dataset")
    infer = sum(1 for item in templates if item.capability_id == "infer_relationships")
    samples = sum(1 for item in templates if item.capability_id == "sample_dataset")
    return profiles, infer, samples, len(templates)


def test_max_tasks_2_keeps_one_profile(selected_assets: tuple[AssetRef, ...]) -> None:
    templates = build_profiling_templates(selected_assets, max_tasks=2)
    profiles, infer, samples, total = _task_counts(templates)
    assert profiles == 1
    assert infer == 1
    assert samples == 0
    assert total == 2
    assert allocate_profiling_slots(asset_count=10, max_tasks=2, sample_asset_limit=3) == (1, 0)


def test_max_tasks_3_keeps_profile_and_optional_sample(
    selected_assets: tuple[AssetRef, ...],
) -> None:
    templates = build_profiling_templates(selected_assets, max_tasks=3)
    profiles, infer, samples, total = _task_counts(templates)
    assert profiles >= 1
    assert infer == 1
    assert total == 3
    assert profiles + infer + samples == 3
    assert allocate_profiling_slots(asset_count=10, max_tasks=3, sample_asset_limit=3) == (1, 1)


def test_max_tasks_normal_profiles_all_selected(selected_assets: tuple[AssetRef, ...]) -> None:
    templates = build_profiling_templates(selected_assets, max_tasks=50)
    profiles, infer, samples, total = _task_counts(templates)
    assert profiles == len(selected_assets)
    assert infer == 1
    assert samples == 3
    assert total == len(selected_assets) + 1 + 3


def test_max_tasks_truncation_keeps_infer(selected_assets: tuple[AssetRef, ...]) -> None:
    templates = build_profiling_templates(selected_assets, max_tasks=6)
    profiles, infer, samples, total = _task_counts(templates)
    assert 1 <= profiles < len(selected_assets)
    assert infer == 1
    assert total <= 6
    assert profiles + infer + samples == total


def test_max_tasks_below_two_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one profile"):
        allocate_profiling_slots(asset_count=10, max_tasks=1, sample_asset_limit=3)


def test_sample_assets_for_zero_limit(selected_assets: tuple[AssetRef, ...]) -> None:
    assert sample_assets_for(selected_assets, limit=0, priority=SAMPLE_PRIORITY_ADDRESSES) == ()


def test_engine_source_has_no_vantara_relationship_list() -> None:
    engine_source = Path("src/aide/profiling/engine.py").read_text(encoding="utf-8")
    join_source = Path("src/aide/profiling/join_candidates.py").read_text(encoding="utf-8")
    assert "KNOWN_RELATIONSHIP_PAIRS" not in engine_source
    assert "EXCLUDED_DEMO_ADDRESSES" not in engine_source
    assert "KNOWN_RELATIONSHIP_PAIRS" not in join_source
    assert "EXCLUDED_DEMO_ADDRESSES" not in join_source


def test_profile_dataset_input_requires_budget() -> None:
    payload = ProfileDatasetInput(
        asset=ORDERS,
        budget=_budget().capability_budget(),
        top_k=3,
    )
    assert payload.budget.max_seconds >= 1
    digest = payload.model_dump(mode="json")
    assert "max_rows" in digest["budget"]
