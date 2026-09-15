"""Least-privilege RO/DEV boundaries. Never grant, revoke, or mutate VANTARA_RAW."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.evaluation.helpers import build_eval_stack, make_call_context

from aide.auth.grants import GrantForgeryError
from aide.capabilities.io import CreateDatasetInput, DiscoverAssetsInput, DiscoveryScope
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.connectors.snowflake.fake import build_fake_pair
from aide.connectors.snowflake.live_probe import (
    interview_live_credentials_available,
    missing_live_secret_names,
)
from aide.domain.benchmark import INTERVIEW_REQUEST
from aide.domain.permissions import PermissionLevel
from aide.domain.sql import AssetKind, AssetRef, SqlText


def test_e_lp_ro_and_dev_allow_lists() -> None:
    assert "VANTARA_RAW" in SNOWFLAKE_RO.allow_list.databases
    assert "AIDE_DEV" in SNOWFLAKE_RO.allow_list.databases
    assert "VANTARA_RAW" not in SNOWFLAKE_DEV.allow_list.databases
    assert "AIDE_DEV" in SNOWFLAKE_DEV.allow_list.databases
    assert "PRODUCTION" not in SNOWFLAKE_DEV.allow_list.databases
    assert "STAGING" not in SNOWFLAKE_DEV.allow_list.databases


@pytest.mark.asyncio
async def test_e_lp_dev_cannot_discover_raw() -> None:
    _ro, dev = build_fake_pair()
    with pytest.raises(SnowflakeMappedError):
        await dev.discover_assets(
            DiscoverAssetsInput(scope=DiscoveryScope(databases=("VANTARA_RAW",))),
            make_call_context(),
        )


@pytest.mark.asyncio
async def test_e_lp_dev_cannot_create_in_raw() -> None:
    _ro, dev = build_fake_pair()
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
            make_call_context(),
        )


@pytest.mark.asyncio
async def test_e_lp_grant_forgery_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path
) -> None:
    supervisor, _ro, _dev, _dbt = build_eval_stack(session_factory, tmp_path)
    with pytest.raises(GrantForgeryError):
        await supervisor.run_customer_revenue(
            INTERVIEW_REQUEST,
            client_supplied_effective=frozenset({PermissionLevel.PRODUCTION_WRITE}),
        )


def test_e_lp_live_is_credential_gated_when_secrets_absent() -> None:
    available = interview_live_credentials_available()
    if available:
        pytest.skip("live credentials present; governed live tests cover E-LP-LIVE")
    missing = missing_live_secret_names()
    assert missing
    assert all(isinstance(name, str) and name for name in missing)
