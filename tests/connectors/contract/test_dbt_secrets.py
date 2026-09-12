from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import unique_key

from aide.connectors.dbt.config import missing_secret_names, snowflake_dbt_settings
from aide.connectors.dbt.contracts import ExecuteTransformationInput
from aide.connectors.dbt.errors import DbtMappedError
from aide.connectors.dbt.real import RealDbtConnector
from aide.connectors.dbt.specs import DBT_DEV
from aide.domain.failures import FailureClass


@pytest.mark.asyncio
async def test_snowflake_target_without_credentials_is_unavailable(tmp_path: Path) -> None:
    settings = snowflake_dbt_settings(tmp_path)
    connector = RealDbtConnector(DBT_DEV, settings)
    snapshot = await connector.health()
    assert snapshot.status == "UNAVAILABLE"
    joined = " ".join(snapshot.reason_codes)
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_DEV" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_PRIVATE_KEY_DEV" in joined
    assert "SECRET_UNRESOLVED:SNOWFLAKE_ACCOUNT" in joined
    assert "DBT_ADAPTER_UNAVAILABLE" not in joined
    for name in settings.required_secret_names():
        assert name in missing_secret_names(settings)
    with pytest.raises(DbtMappedError) as exc:
        await connector.execute_transformation(
            ExecuteTransformationInput(project_state_id=uuid4()),
            make_context(operation_idempotency_key=unique_key("run")),
        )
    assert exc.value.failure is FailureClass.CONNECTOR_FAILURE
    assert "SECRET_UNRESOLVED" in str(exc.value)
    await connector.close()


@pytest.mark.asyncio
async def test_partial_snowflake_env_does_not_echo_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "dummy_account_value_xyz")
    settings = snowflake_dbt_settings(tmp_path)
    connector = RealDbtConnector(DBT_DEV, settings)
    snapshot = await connector.health()
    assert snapshot.status == "UNAVAILABLE"
    assert "dummy_account_value_xyz" not in " ".join(snapshot.reason_codes)
    assert "SECRET_UNRESOLVED:SNOWFLAKE_ACCOUNT" not in " ".join(snapshot.reason_codes)
    assert "SECRET_UNRESOLVED:SNOWFLAKE_USER_DEV" in " ".join(snapshot.reason_codes)
    await connector.close()
