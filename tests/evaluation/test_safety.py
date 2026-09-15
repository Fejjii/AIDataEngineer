"""Repair and policy safety: prohibited actions fail closed."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.evaluation.helpers import build_eval_stack, make_call_context
from tests.helpers import policy_request, read_sql
from tests.unit.repair.test_validate_repair import (
    ORIGINAL_SQL,
    _input,
    _proposal,
    _reasons,
)
from tests.unit.repair.test_validate_repair import (
    _budget as repair_budget,
)
from tests.unit.repair.test_validate_repair import (
    _drift as repair_drift,
)

from aide.auth.grants import GrantAuthorizer, GrantForgeryError
from aide.capabilities.io import Budget, CreateDatasetInput, ExecuteQueryInput
from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.connectors.snowflake.fake import build_fake_pair
from aide.domain.benchmark import INTERVIEW_REQUEST
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.sql import AssetKind, AssetRef, SqlText
from aide.persistence.models import GatewayDispatchIntentModel
from aide.policy.engine import PolicyEngine
from aide.policy.reasons import ReasonCode
from aide.repair.diff import sha256_text
from aide.repair.validate import validate_repair


def test_second_repair_is_rejected() -> None:
    result = validate_repair(_input(budget=repair_budget(applied_count=1)))
    assert not result.allowed
    assert "SECOND_REPAIR" in _reasons(result)


def test_recursive_repair_is_rejected() -> None:
    result = validate_repair(_input(budget=repair_budget(recursive_requested=True)))
    assert not result.allowed
    assert "RECURSIVE_REPAIR" in _reasons(result)


def test_broader_sql_diff_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace(
        "INVOICE_STATUS as invoice_status",
        "STATUS as invoice_status,\n  1 as extra",
    )
    drift = repair_drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "BROADER_PARSED_DIFF" in _reasons(result) or "GRAIN_CHANGED" in _reasons(result)


def test_wrong_table_is_rejected() -> None:
    drift = repair_drift(
        asset=AssetRef(
            connector_id="snowflake_ro",
            address=("VANTARA_RAW", "BILLING", "PAYMENTS"),
            kind=AssetKind.TABLE,
            platform_type="snowflake",
        )
    )
    result = validate_repair(_input(drift=drift, proposal=_proposal(drift, asset=drift.asset)))
    assert not result.allowed
    assert "WRONG_TABLE" in _reasons(result)


def test_wrong_column_is_rejected() -> None:
    drift = repair_drift()
    proposal = _proposal(drift, from_column="CUSTOMER_ID", to_column="CUST_ID")
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "DIFFERENT_COLUMN_RENAME" in _reasons(result)


def test_type_mismatch_is_rejected() -> None:
    drift = repair_drift(old_data_type="VARCHAR", new_data_type="NUMBER")
    result = validate_repair(_input(drift=drift, proposal=_proposal(drift)))
    assert not result.allowed
    assert "DIFFERENT_NORMALIZED_TYPE" in _reasons(result)


def test_test_weakening_is_rejected() -> None:
    original = "version: 2\nmodels:\n  - name: x\n    tests:\n      - unique\n"
    patched = (
        "version: 2\nmodels:\n  - name: x\n    tests:\n      - unique:\n"
        "          config:\n            severity: warn\n"
    )
    drift = repair_drift()
    proposal = _proposal(drift, artifact_path="models/schema.yml").model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(
        _input(
            drift=drift,
            proposal=proposal,
            original_sql=original,
            files=(("models/schema.yml", original, "SCHEMA_YML"),),
        )
    )
    assert not result.allowed
    assert "TEST_WEAKENED" in _reasons(result) or "YAML_CHANGED" in _reasons(result)


def test_permission_escalation_request_is_stripped() -> None:
    actor_id = uuid4()
    from aide.domain.principal import PrincipalRef, Role

    actor = PrincipalRef(
        principal_id=actor_id,
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=uuid4(),
    )
    grants = GrantAuthorizer().authorize(
        actor,
        frozenset(
            {
                PermissionLevel.READ,
                PermissionLevel.PRODUCTION_WRITE,
                PermissionLevel.SECURITY,
                PermissionLevel.STAGING_DEPLOY,
            }
        ),
        target_environment=TargetEnv.DEV,
        decided_at=datetime.now(UTC).replace(tzinfo=None),
    )
    assert PermissionLevel.PRODUCTION_WRITE not in grants.effective
    assert PermissionLevel.SECURITY not in grants.effective
    assert PermissionLevel.STAGING_DEPLOY not in grants.effective


def test_production_and_staging_targets_are_denied() -> None:
    prod = PolicyEngine().evaluate(policy_request(env=TargetEnv.PROD, sql=read_sql()))
    assert prod.decision == "DENY"
    assert ReasonCode.PROD_DISABLED_V1 in prod.reasons
    staging = PolicyEngine().evaluate(policy_request(env=TargetEnv.STAGING, sql=read_sql()))
    assert staging.decision == "DENY"
    assert ReasonCode.ENV_MISMATCH in staging.reasons


@pytest.mark.asyncio
async def test_raw_mutation_and_dev_raw_create_fail_closed() -> None:
    ro, dev = build_fake_pair()
    context = make_call_context()
    with pytest.raises(SnowflakeMappedError):
        await ro.execute_query(
            ExecuteQueryInput(
                sql=SqlText(
                    dialect="snowflake",
                    text="INSERT INTO VANTARA_RAW.BILLING.INVOICES (INVOICE_ID) VALUES (1)",
                ),
                budget=Budget(max_rows=10, max_bytes=1024, max_seconds=5),
            ),
            context,
        )
    with pytest.raises(SnowflakeMappedError):
        await dev.create_dataset(
            CreateDatasetInput(
                target=AssetRef(
                    connector_id="snowflake_dev",
                    address=("VANTARA_RAW", "BILLING", "EVIL"),
                    kind=AssetKind.TABLE,
                    platform_type="snowflake",
                ),
                definition=SqlText(
                    dialect="snowflake",
                    text='CREATE TABLE "VANTARA_RAW"."BILLING"."EVIL" (ID NUMBER)',
                ),
            ),
            context,
        )


def test_supervisor_cannot_bypass_tool_gateway_imports() -> None:
    """E-SF-BYPASS: Supervisor and Gateway never import vendor fakes or real clients."""
    supervisor = Path("src/aide/app/supervisor.py").read_text(encoding="utf-8")
    gateway = Path("src/aide/app/gateway.py").read_text(encoding="utf-8")
    banned = (
        "aide.connectors.snowflake.fake",
        "aide.connectors.snowflake.real",
        "aide.connectors.dbt.fake",
        "aide.connectors.dbt.real",
    )
    for module in banned:
        assert module not in supervisor
        assert module not in gateway


@pytest.mark.asyncio
async def test_direct_connector_dispatch_creates_no_gateway_intent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """E-SF-DIRECT: calling a connector outside the gateway records no dispatch intent."""
    ro, _dev = build_fake_pair()
    from aide.capabilities.io import DiscoverAssetsInput, DiscoveryScope

    await ro.discover_assets(
        DiscoverAssetsInput(scope=DiscoveryScope(databases=("VANTARA_RAW",))),
        make_call_context(),
    )
    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(GatewayDispatchIntentModel))
    assert count == 0


@pytest.mark.asyncio
async def test_client_grant_forgery_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    with pytest.raises(GrantForgeryError):
        await supervisor.run_customer_revenue(
            INTERVIEW_REQUEST,
            client_supplied_effective=frozenset({PermissionLevel.PRODUCTION_WRITE}),
        )
