from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.connectors.contract.conftest import (
    DEV_HANDLERS,
    RO_HANDLERS,
    make_context,
)

from aide.capabilities.io import (
    Budget,
    CreateDatasetInput,
    DescribeAssetInput,
    DetectSchemaDriftInput,
    DiscoverAssetsInput,
    DiscoveryFilters,
    DiscoveryScope,
    DropDatasetInput,
    ExecuteQueryInput,
    InferRelationshipsInput,
    MetricsQueryInput,
    ProfileDatasetInput,
    SampleDatasetInput,
    ValidateQueryInput,
)
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.context import RecoveryContext
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.registry import startup_permission_check
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.snowflake.config import snowflake_credentials_available
from aide.connectors.snowflake.dialect import normalize_identifier, parse_round_trip, statement_type
from aide.connectors.snowflake.errors import SnowflakeMappedError, map_error
from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.connectors.snowflake.namespace import workflow_short_id
from aide.connectors.snowflake.query_tags import parse_query_tag
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO
from aide.domain.enums import TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.permissions import PermissionLevel
from aide.domain.sql import AssetKind, AssetRef, SqlText
from aide.domain.versions import CapabilityContractRef

BUDGET = Budget(max_rows=20, max_bytes=65536, max_seconds=30)


def _orders() -> AssetRef:
    return AssetRef(
        connector_id="snowflake_ro",
        address=("RAW", "SALES", "ORDERS"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )


def test_capability_advertisements_and_permissions() -> None:
    capabilities = kernel_registry()
    startup_permission_check(SNOWFLAKE_RO, capabilities.required_permissions())
    startup_permission_check(SNOWFLAKE_DEV, capabilities.required_permissions())
    startup_permission_check(FAKE_SNOWFLAKE_RO, capabilities.required_permissions())
    startup_permission_check(FAKE_SNOWFLAKE_DEV, capabilities.required_permissions())
    for capability_id in RO_HANDLERS:
        assert SNOWFLAKE_RO.advertises(capability_id, 1)
        assert FAKE_SNOWFLAKE_RO.advertises(capability_id, 1)
        assert not SNOWFLAKE_DEV.advertises(capability_id)
        assert not FAKE_SNOWFLAKE_DEV.advertises(capability_id)
    for capability_id in DEV_HANDLERS:
        assert SNOWFLAKE_DEV.advertises(capability_id, 1)
        assert not SNOWFLAKE_RO.advertises(capability_id)
    assert PermissionLevel.READ in SNOWFLAKE_RO.allowed_permissions
    assert PermissionLevel.READ not in SNOWFLAKE_DEV.allowed_permissions
    assert SNOWFLAKE_RO.identity_class.value == "READ_ONLY"
    assert SNOWFLAKE_DEV.identity_class.value == "DEVELOPMENT"
    assert SNOWFLAKE_RO.advertises("evaluate_execution_policy", 1)
    assert not SNOWFLAKE_DEV.advertises("evaluate_execution_policy")


def test_fake_and_real_handler_parity_structure() -> None:
    fake_ro = FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)
    fake_dev = FakeSnowflakeConnector(FAKE_SNOWFLAKE_DEV)
    real_ro = RealSnowflakeConnector(SNOWFLAKE_RO)
    real_dev = RealSnowflakeConnector(SNOWFLAKE_DEV)
    for name in RO_HANDLERS + DEV_HANDLERS:
        assert callable(getattr(fake_ro, name))
        assert callable(getattr(real_ro, name))
        assert callable(getattr(fake_dev, name))
        assert callable(getattr(real_dev, name))


@pytest.mark.asyncio
async def test_ro_identity_rejects_writes(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context()
    schema = f"{workflow_short_id(context.workflow_id)}_MARTS"
    target = AssetRef(
        connector_id="snowflake_dev",
        address=("AIDE_DEV", schema, "T"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.create_dataset(
            CreateDatasetInput(
                target=target,
                definition=SqlText(
                    dialect="snowflake",
                    text=f"CREATE TABLE AIDE_DEV.{schema}.T AS SELECT 1 AS ID",
                ),
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.PERMISSION_FAILURE


@pytest.mark.asyncio
async def test_dev_identity_rejects_reads(fake_dev: FakeSnowflakeConnector) -> None:
    context = make_context()
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_dev.discover_assets(
            DiscoverAssetsInput(scope=DiscoveryScope(databases=("RAW",))),
            context,
        )
    assert map_error(exc.value) is FailureClass.PERMISSION_FAILURE
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_dev.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELECT 1"),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.PERMISSION_FAILURE


@pytest.mark.asyncio
async def test_vantara_raw_is_on_ro_allow_list(fake_ro: FakeSnowflakeConnector) -> None:
    assert "VANTARA_RAW" in SNOWFLAKE_RO.allow_list.databases
    assert "RAW" in SNOWFLAKE_RO.allow_list.databases
    assert "VANTARA_RAW" in FAKE_SNOWFLAKE_RO.allow_list.databases
    assert "VANTARA_RAW" not in SNOWFLAKE_DEV.allow_list.databases
    context = make_context()
    discovered = await fake_ro.discover_assets(
        DiscoverAssetsInput(scope=DiscoveryScope(databases=("VANTARA_RAW",))),
        context,
    )
    assert discovered.snapshot_id
    assert all(asset.address[0] == "VANTARA_RAW" for asset in discovered.assets)


@pytest.mark.asyncio
async def test_allow_list_enforcement(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context()
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.discover_assets(
            DiscoverAssetsInput(scope=DiscoveryScope(databases=("FORBIDDEN",))),
            context,
        )
    assert map_error(exc.value) is FailureClass.PERMISSION_FAILURE


@pytest.mark.asyncio
async def test_ro_read_capabilities_on_fake_catalogue(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context()
    discovered = await fake_ro.discover_assets(
        DiscoverAssetsInput(
            scope=DiscoveryScope(databases=("RAW",)),
            filters=DiscoveryFilters(),
        ),
        context,
    )
    assert discovered.assets
    assert all(asset.address[0] == "RAW" for asset in discovered.assets)
    described = await fake_ro.describe_asset(DescribeAssetInput(asset=_orders()), context)
    assert described.columns
    assert described.primary_key == ("ORDER_ID",)
    baseline = described.columns
    drifted = await fake_ro.detect_schema_drift(
        DetectSchemaDriftInput(
            asset=_orders(),
            baseline_snapshot_id=described.snapshot_id,
            baseline_columns=baseline,
        ),
        context,
    )
    assert drifted.drifted is False
    profile = await fake_ro.profile_dataset(
        ProfileDatasetInput(asset=_orders(), budget=BUDGET, top_k=3),
        context,
    )
    assert profile.row_count == 3
    assert all(0 <= col.null_ratio <= 1 for col in profile.columns)
    sample = await fake_ro.sample_dataset(SampleDatasetInput(asset=_orders(), n=2), context)
    assert len(sample.rows) <= 2
    inferred = await fake_ro.infer_relationships(
        InferRelationshipsInput(
            assets=(
                _orders(),
                AssetRef(
                    connector_id="snowflake_ro",
                    address=("RAW", "SALES", "CUSTOMERS"),
                    kind=AssetKind.TABLE,
                    platform_type="snowflake",
                ),
            ),
            max_pairs=8,
            budget=BUDGET,
        ),
        context,
    )
    assert inferred.candidates
    valid = await fake_ro.validate_query(
        ValidateQueryInput(
            sql=SqlText(dialect="snowflake", text="SELECT AMOUNT FROM RAW.SALES.ORDERS")
        ),
        context,
    )
    assert valid.valid is True
    executed = await fake_ro.execute_query(
        ExecuteQueryInput(
            sql=SqlText(dialect="snowflake", text="SELECT AMOUNT FROM RAW.SALES.ORDERS"),
            budget=BUDGET,
        ),
        context,
    )
    assert executed.row_count == 3
    assert executed.query_tag is not None
    parsed = parse_query_tag(executed.query_tag)
    assert parsed.operation_idempotency_key == context.operation_idempotency_key
    metrics = await fake_ro.get_execution_metrics(
        MetricsQueryInput(query_tag=executed.query_tag, since=datetime.now(UTC)),
        context,
    )
    assert metrics.queries
    costs = await fake_ro.get_cost_metrics(
        MetricsQueryInput(query_tag=executed.query_tag, since=datetime.now(UTC)),
        context,
    )
    assert costs.complete is False
    assert costs.currency == "USD"
    fake_ro.rename_column(("RAW", "SALES", "ORDERS"), "AMOUNT", "ORDER_AMOUNT")
    drifted_after = await fake_ro.detect_schema_drift(
        DetectSchemaDriftInput(
            asset=_orders(),
            baseline_snapshot_id=described.snapshot_id,
            baseline_columns=baseline,
        ),
        context,
    )
    assert drifted_after.drifted is True


@pytest.mark.asyncio
async def test_query_tag_round_trip_on_execute(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context()
    executed = await fake_ro.execute_query(
        ExecuteQueryInput(
            sql=SqlText(dialect="snowflake", text="SELECT 1 AS ID FROM RAW.SALES.ORDERS"),
            budget=BUDGET,
        ),
        context,
    )
    parsed = parse_query_tag(executed.query_tag or "")
    assert parsed.workflow_id == context.workflow_id
    assert parsed.attempt_id == context.attempt_id
    assert parsed.attempt_number == 1
    assert len(parsed.operation_idempotency_key) == 64


@pytest.mark.asyncio
async def test_deadline_timeout(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context(deadline_seconds=-1)
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELECT 1"),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.TIMEOUT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        FailureClass.SQL_SYNTAX,
        FailureClass.MISSING_OBJECT,
        FailureClass.SCHEMA_MISMATCH,
        FailureClass.TYPE_MISMATCH,
        FailureClass.PERMISSION_FAILURE,
        FailureClass.TIMEOUT,
        FailureClass.TRANSIENT_PROVIDER,
        FailureClass.RESOURCE_LIMIT,
    ],
)
async def test_error_injection_and_mapping(
    fake_ro: FakeSnowflakeConnector, failure: FailureClass
) -> None:
    context = make_context()
    fake_ro.fail_next("execute_query", failure)
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELECT 1 FROM RAW.SALES.ORDERS"),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is failure


@pytest.mark.asyncio
async def test_execute_query_allow_list_and_read_only(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context()
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELECT 1 FROM FORBIDDEN.X.Y"),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.PERMISSION_FAILURE
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.execute_query(
            ExecuteQueryInput(
                sql=SqlText(
                    dialect="snowflake",
                    text="INSERT INTO RAW.SALES.ORDERS (ORDER_ID) VALUES (9)",
                ),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.UNSAFE_OPERATION
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_ro.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELEKT 1"),
                budget=BUDGET,
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.SQL_SYNTAX


@pytest.mark.asyncio
async def test_dev_namespace_and_drop(fake_dev: FakeSnowflakeConnector) -> None:
    context = make_context()
    schema = f"{workflow_short_id(context.workflow_id)}_MARTS"
    target = AssetRef(
        connector_id="snowflake_dev",
        address=("AIDE_DEV", schema, "ORDERS_COPY"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    created = await fake_dev.create_dataset(
        CreateDatasetInput(
            target=target,
            definition=SqlText(
                dialect="snowflake",
                text=f"CREATE TABLE AIDE_DEV.{schema}.ORDERS_COPY AS SELECT 1 AS ID",
            ),
        ),
        context,
    )
    assert created.created.address[1].startswith(workflow_short_id(context.workflow_id) + "_")
    outside = AssetRef(
        connector_id="snowflake_dev",
        address=("AIDE_DEV", "PUBLIC", "ORDERS"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    with pytest.raises(SnowflakeMappedError) as exc:
        await fake_dev.create_dataset(
            CreateDatasetInput(
                target=outside,
                definition=SqlText(
                    dialect="snowflake",
                    text="CREATE TABLE AIDE_DEV.PUBLIC.ORDERS AS SELECT 1 AS ID",
                ),
            ),
            context,
        )
    assert map_error(exc.value) is FailureClass.UNSAFE_OPERATION
    dropped = await fake_dev.drop_dataset(
        DropDatasetInput(target=target, created_by_workflow=context.workflow_id),
        context,
    )
    assert dropped.dropped is True


@pytest.mark.asyncio
async def test_reconciliation_prefers_query_id_and_tag(fake_ro: FakeSnowflakeConnector) -> None:
    context = make_context()
    executed = await fake_ro.execute_query(
        ExecuteQueryInput(
            sql=SqlText(dialect="snowflake", text="SELECT AMOUNT FROM RAW.SALES.ORDERS"),
            budget=BUDGET,
        ),
        context,
    )
    from aide.connectors.base.context import AttemptRecoveryRef

    recovery = RecoveryContext(
        workflow_id=context.workflow_id,
        phase_run_id=context.phase_run_id,
        task_id=context.task_id,
        operation_idempotency_key=context.operation_idempotency_key,
        resolved_input_digest=context.resolved_input_digest,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id="execute_query",
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        attempts=(
            AttemptRecoveryRef(
                attempt_id=context.attempt_id,
                attempt_number=1,
                query_id=executed.query_id,
            ),
        ),
        reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    found = await fake_ro.reconcile(recovery)
    assert isinstance(found, EffectFound)
    assert found.external_ref == executed.query_id
    tag_recovery = RecoveryContext(
        workflow_id=context.workflow_id,
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key=context.operation_idempotency_key,
        resolved_input_digest=context.resolved_input_digest,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id="execute_query",
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        attempts=(),
        operation_locator={"query_tag": executed.query_tag or ""},
        reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    # effects store still matches the operation key
    tagged = await fake_ro.reconcile(tag_recovery)
    assert isinstance(tagged, EffectFound)
    missing = RecoveryContext(
        workflow_id=uuid4(),
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key="c" * 64,
        resolved_input_digest="d" * 64,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id="execute_query",
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        attempts=(),
        reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    absent = await fake_ro.reconcile(missing)
    assert isinstance(absent, NoEffect)
    fake_ro.mark_in_progress("e" * 64, "qid-running")
    running = RecoveryContext(
        workflow_id=uuid4(),
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key="e" * 64,
        resolved_input_digest="f" * 64,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id="execute_query",
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        attempts=(),
        reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    progress = await fake_ro.reconcile(running)
    assert isinstance(progress, InProgress)
    fake_ro.set_history_lag(True)
    lagged = await fake_ro.reconcile(missing)
    assert isinstance(lagged, Unknown)


@pytest.mark.asyncio
async def test_fail_after_effect_still_reconciles(fake_dev: FakeSnowflakeConnector) -> None:
    context = make_context()
    schema = f"{workflow_short_id(context.workflow_id)}_MARTS"
    target = AssetRef(
        connector_id="snowflake_dev",
        address=("AIDE_DEV", schema, "CRASH"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    fake_dev.fail_after_effect("create_dataset")
    with pytest.raises(SnowflakeMappedError):
        await fake_dev.create_dataset(
            CreateDatasetInput(
                target=target,
                definition=SqlText(
                    dialect="snowflake",
                    text=f"CREATE TABLE AIDE_DEV.{schema}.CRASH AS SELECT 1 AS ID",
                ),
            ),
            context,
        )
    recovered = await fake_dev.reconcile(
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


@pytest.mark.asyncio
async def test_real_without_credentials_skips_live_and_fails_closed() -> None:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    snapshot = await connector.health()
    assert snapshot.status == "UNAVAILABLE"
    context = make_context()
    with pytest.raises(Exception) as exc:
        await connector.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text="SELECT 1"),
                budget=BUDGET,
            ),
            context,
        )
    assert "SECRET_UNRESOLVED" in str(exc.value)
    recovery = RecoveryContext(
        workflow_id=context.workflow_id,
        phase_run_id=context.phase_run_id,
        task_id=context.task_id,
        operation_idempotency_key=context.operation_idempotency_key,
        resolved_input_digest=context.resolved_input_digest,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id="execute_query",
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        attempts=(),
        reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
    )
    reconciled = await connector.reconcile(recovery)
    assert isinstance(reconciled, Unknown)
    assert "SECRET_UNRESOLVED" in reconciled.reason


@pytest.mark.snowflake_live
@pytest.mark.skipif(
    not snowflake_credentials_available(),
    reason="Snowflake credentials unavailable",
)
@pytest.mark.asyncio
async def test_real_live_discover_vantara_raw() -> None:
    """DE005B live scaffold: discover the accepted Vantara demo source database."""
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    context = make_context()
    result = await connector.discover_assets(
        DiscoverAssetsInput(scope=DiscoveryScope(databases=("VANTARA_RAW",))),
        context,
    )
    assert result.snapshot_id
    assert all(asset.address[0] == "VANTARA_RAW" for asset in result.assets)


def test_dialect_round_trip_and_namespace() -> None:
    tree = parse_round_trip("SELECT amount FROM RAW.SALES.ORDERS")
    assert tree is not None
    assert statement_type("SELECT 1") == "SELECT"
    assert normalize_identifier("orders") == "ORDERS"
    assert normalize_identifier('"keepCase"') == "keepCase"
    wf = uuid4()
    short = workflow_short_id(wf)
    assert short.startswith("WF")
    assert len(short) == 8
