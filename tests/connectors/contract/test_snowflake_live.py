from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from synthetic.vantara.export.snowflake_load import expected_v2_row_counts
from tests.connectors.contract.conftest import RO_HANDLERS, make_context

from aide.capabilities.io import (
    Budget,
    CreateDatasetInput,
    DescribeAssetInput,
    DiscoverAssetsInput,
    DiscoveryScope,
    DropDatasetInput,
    ExecuteQueryInput,
    InferRelationshipsInput,
    MetricsQueryInput,
    ProfileDatasetInput,
    SampleDatasetInput,
    ValidateQueryInput,
)
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.reconcile import EffectFound
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.snowflake.config import (
    ROLE_DEVELOPMENT,
    ROLE_READ_ONLY,
    snowflake_credentials_available,
    snowflake_dev_credentials_available,
)
from aide.connectors.snowflake.errors import SnowflakeMappedError, map_error
from aide.connectors.snowflake.masking import column_is_sensitive
from aide.connectors.snowflake.namespace import workflow_short_id
from aide.connectors.snowflake.query_tags import parse_query_tag
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.domain.enums import TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef, SqlText
from aide.domain.versions import CapabilityContractRef

pytestmark = [
    pytest.mark.snowflake_live,
    pytest.mark.skipif(
        not snowflake_credentials_available(),
        reason="Snowflake credentials unavailable",
    ),
]

BUDGET = Budget(max_rows=20, max_bytes=65536, max_seconds=60)

REQUIRED_SCHEMAS = frozenset({"CRM", "BILLING", "PAYMENTS", "PRODUCT", "SUPPORT"})
REQUIRED_TABLES = frozenset(
    {
        ("CRM", "ACCOUNTS"),
        ("CRM", "CONTACTS"),
        ("CRM", "OPPORTUNITIES"),
        ("CRM", "ACCOUNT_CROSSWALK"),
        ("BILLING", "CUSTOMERS"),
        ("BILLING", "SUBSCRIPTIONS"),
        ("BILLING", "INVOICES"),
        ("BILLING", "INVOICE_LINES"),
        ("PAYMENTS", "PAYMENTS"),
        ("PAYMENTS", "REFUNDS"),
        ("PRODUCT", "PLANS"),
        ("SUPPORT", "TICKETS"),
    }
)


def _asset(schema: str, table: str) -> AssetRef:
    return AssetRef(
        connector_id="snowflake_ro",
        address=("VANTARA_RAW", schema, table),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )


def _discovered_tables(assets: tuple[object, ...]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for asset in assets:
        address = getattr(asset, "address", ())
        parts = [str(part) for part in address]
        if len(parts) >= 3:
            found.add((parts[1], parts[2]))
    return found


def expected_tiny_row_counts() -> dict[str, int]:
    return expected_v2_row_counts(Path("synthetic/vantara/fixtures/tiny/v2/csv"))


def _row_count_sql() -> str:
    parts = [
        (
            f"SELECT '{schema}.{table}' AS TABLE_NAME, COUNT(*) AS N "
            f"FROM VANTARA_RAW.{schema}.{table}"
        )
        for schema, table in sorted(REQUIRED_TABLES)
    ]
    return " UNION ALL ".join(parts)


def _norm_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).upper(): value for key, value in row.items()}


def role_mismatch_absent(reason_codes: tuple[str, ...]) -> bool:
    return "ROLE_MISMATCH" not in reason_codes


async def assert_vantara_raw_populated(
    connector: RealSnowflakeConnector,
    context: CallContext,
) -> dict[str, int]:
    expected = expected_tiny_row_counts()
    counted = await connector.execute_query(
        ExecuteQueryInput(
            sql=SqlText(dialect="snowflake", text=_row_count_sql()),
            budget=Budget(max_rows=32, max_bytes=65536, max_seconds=60),
        ),
        context,
    )
    assert counted.rows, "VANTARA_RAW row-count query returned no rows"
    loaded: dict[str, int] = {}
    for row in counted.rows:
        normalized = _norm_row(row)
        name = normalized.get("TABLE_NAME")
        count = normalized.get("N")
        if name is None or count is None:
            continue
        loaded[str(name)] = int(count)
    missing_counts = REQUIRED_TABLES - {
        (name.split(".", 1)[0], name.split(".", 1)[1]) for name in loaded if "." in name
    }
    assert not missing_counts, f"missing COUNT(*) results: {sorted(missing_counts)}"
    empty = {name: n for name, n in loaded.items() if n <= 0}
    assert not empty, f"empty VANTARA_RAW tables cannot pass: {empty}"
    mismatched = {
        name: (loaded[name], expected[name])
        for name in expected
        if loaded.get(name) != expected[name]
    }
    assert not mismatched, f"VANTARA_RAW row counts differ from tiny v2 CSVs: {mismatched}"
    return loaded


@pytest.mark.asyncio
async def test_live_ro_health_role_and_discovery() -> None:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    snapshot = await connector.health()
    assert snapshot.status == "AVAILABLE"
    assert role_mismatch_absent(snapshot.reason_codes)
    context = make_context(deadline_seconds=90)
    role = await connector.execute_query(
        ExecuteQueryInput(
            sql=SqlText(dialect="snowflake", text="SELECT CURRENT_ROLE() AS ROLE"),
            budget=BUDGET,
        ),
        context,
    )
    assert role.rows
    assert str(next(iter(role.rows[0].values()))).upper() == ROLE_READ_ONLY
    result = await connector.discover_assets(
        DiscoverAssetsInput(scope=DiscoveryScope(databases=("VANTARA_RAW",))),
        context,
    )
    assert result.assets, "empty VANTARA_RAW must not pass live discovery"
    assert all(asset.address[0] == "VANTARA_RAW" for asset in result.assets)
    schemas = {asset.address[1] for asset in result.assets if len(asset.address) >= 3}
    assert schemas >= REQUIRED_SCHEMAS
    tables = _discovered_tables(result.assets)
    missing = REQUIRED_TABLES - tables
    assert not missing, f"missing required Vantara tables: {sorted(missing)}"
    await assert_vantara_raw_populated(connector, context)
    await connector.close()


@pytest.mark.asyncio
async def test_live_ro_describe_profile_sample_relationships_and_query() -> None:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    context = make_context(deadline_seconds=120)
    accounts = _asset("CRM", "ACCOUNTS")
    contacts = _asset("CRM", "CONTACTS")
    plans = _asset("PRODUCT", "PLANS")
    described = await connector.describe_asset(DescribeAssetInput(asset=accounts), context)
    assert described.columns
    assert any(col.name == "ACCOUNT_ID" for col in described.columns)
    expected = expected_tiny_row_counts()
    profile = await connector.profile_dataset(
        ProfileDatasetInput(asset=plans, budget=BUDGET, top_k=3),
        context,
    )
    assert profile.row_count == expected["PRODUCT.PLANS"]
    sample = await connector.sample_dataset(SampleDatasetInput(asset=contacts, n=5), context)
    assert sample.rows
    assert any(column_is_sensitive(name) for name in sample.masked_columns)
    inferred = await connector.infer_relationships(
        InferRelationshipsInput(assets=(accounts, contacts), max_pairs=8, budget=BUDGET),
        context,
    )
    assert inferred.relationships_id
    assert inferred.candidates, "ACCOUNT_ID relationship between ACCOUNTS and CONTACTS missing"
    valid = await connector.validate_query(
        ValidateQueryInput(
            sql=SqlText(
                dialect="snowflake",
                text="SELECT PLAN_CODE FROM VANTARA_RAW.PRODUCT.PLANS",
            )
        ),
        context,
    )
    assert valid.valid is True
    since = datetime.now(UTC)
    executed = await connector.execute_query(
        ExecuteQueryInput(
            sql=SqlText(
                dialect="snowflake",
                text="SELECT PLAN_CODE FROM VANTARA_RAW.PRODUCT.PLANS",
            ),
            budget=BUDGET,
        ),
        context,
    )
    assert executed.row_count > 0
    assert executed.query_tag is not None
    parsed = parse_query_tag(executed.query_tag)
    assert parsed.operation_idempotency_key == context.operation_idempotency_key
    metrics = None
    for _ in range(8):
        metrics = await connector.get_execution_metrics(
            MetricsQueryInput(query_tag=executed.query_tag, since=since),
            context,
        )
        if metrics.queries:
            break
        await asyncio.sleep(2)
    assert metrics is not None
    assert metrics.queries, "QUERY_HISTORY did not return the tagged live query"
    costs = await connector.get_cost_metrics(
        MetricsQueryInput(query_tag=executed.query_tag, since=since),
        context,
    )
    assert costs.currency == "USD"
    assert costs.credits_used > 0
    await connector.close()


@pytest.mark.asyncio
async def test_live_deadline_timeout() -> None:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    context = make_context(deadline_seconds=-1)
    with pytest.raises(SnowflakeMappedError) as exc:
        await connector.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELECT CURRENT_ROLE() AS ROLE"),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.TIMEOUT
    await connector.close()


@pytest.mark.asyncio
@pytest.mark.skipif(
    not snowflake_dev_credentials_available(),
    reason="Snowflake DEV credentials unavailable",
)
async def test_live_dev_namespace_write_reject_reconcile_and_cleanup() -> None:
    assert not any(SNOWFLAKE_DEV.advertises(item) for item in RO_HANDLERS)
    connector = RealSnowflakeConnector(SNOWFLAKE_DEV)
    snapshot = await connector.health()
    assert snapshot.status == "AVAILABLE"
    assert role_mismatch_absent(snapshot.reason_codes)
    assert ROLE_DEVELOPMENT == "AIDE_DEV_RW"
    context = make_context(deadline_seconds=90)
    schema = f"{workflow_short_id(context.workflow_id)}_LIVE"
    target = AssetRef(
        connector_id="snowflake_dev",
        address=("AIDE_DEV", schema, "PROBE"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    outside_raw = AssetRef(
        connector_id="snowflake_dev",
        address=("VANTARA_RAW", "CRM", "ACCOUNTS"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    outside_ns = AssetRef(
        connector_id="snowflake_dev",
        address=("AIDE_DEV", "PUBLIC", "ORDERS"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    created = None
    try:
        with pytest.raises(SnowflakeMappedError) as raw_exc:
            await connector.create_dataset(
                CreateDatasetInput(
                    target=outside_raw,
                    definition=SqlText(
                        dialect="snowflake",
                        text="CREATE TABLE VANTARA_RAW.CRM.SHOULD_NOT_EXIST AS SELECT 1 AS ID",
                    ),
                ),
                context,
            )
        assert map_error(raw_exc.value) in {
            FailureClass.PERMISSION_FAILURE,
            FailureClass.UNSAFE_OPERATION,
        }
        with pytest.raises(SnowflakeMappedError) as ns_exc:
            await connector.create_dataset(
                CreateDatasetInput(
                    target=outside_ns,
                    definition=SqlText(
                        dialect="snowflake",
                        text="CREATE TABLE AIDE_DEV.PUBLIC.ORDERS AS SELECT 1 AS ID",
                    ),
                ),
                context,
            )
        assert map_error(ns_exc.value) is FailureClass.UNSAFE_OPERATION
        created = await connector.create_dataset(
            CreateDatasetInput(
                target=target,
                definition=SqlText(
                    dialect="snowflake",
                    text=f"CREATE TABLE AIDE_DEV.{schema}.PROBE AS SELECT 1 AS ID",
                ),
            ),
            context,
        )
        assert created.created.address[1].startswith(workflow_short_id(context.workflow_id) + "_")
        recovered = await connector.reconcile(
            RecoveryContext(
                workflow_id=context.workflow_id,
                phase_run_id=context.phase_run_id,
                task_id=context.task_id,
                operation_idempotency_key=context.operation_idempotency_key,
                resolved_input_digest=context.resolved_input_digest,
                resolved_input_schema_version=1,
                capability=CapabilityContractRef(
                    capability_id="create_dataset",
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
                connector_id="snowflake_dev",
                connector_version="1.0.0",
                target_environment=TargetEnv.DEV,
                attempts=(),
                operation_locator={"target": ".".join(target.address)},
                reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
            )
        )
        assert isinstance(recovered, EffectFound)
        dropped = await connector.drop_dataset(
            DropDatasetInput(target=target, created_by_workflow=context.workflow_id),
            context,
        )
        assert dropped.dropped is True
        after_drop = await connector.reconcile(
            RecoveryContext(
                workflow_id=context.workflow_id,
                phase_run_id=uuid4(),
                task_id=context.task_id,
                operation_idempotency_key="b" * 64,
                resolved_input_digest=context.resolved_input_digest,
                resolved_input_schema_version=1,
                capability=CapabilityContractRef(
                    capability_id="drop_dataset",
                    capability_contract_version=1,
                    input_schema_version=1,
                    output_schema_version=1,
                ),
                connector_id="snowflake_dev",
                connector_version="1.0.0",
                target_environment=TargetEnv.DEV,
                attempts=(),
                operation_locator={"target": ".".join(target.address)},
                reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
            )
        )
        assert isinstance(after_drop, EffectFound)
        created = None
    finally:
        if created is not None:
            await connector.drop_dataset(
                DropDatasetInput(target=target, created_by_workflow=context.workflow_id),
                context,
            )
        await connector.close()
