from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from aide.connectors.base.context import CallContext, RedactionPolicy
from aide.connectors.snowflake.config import OPTIONAL_SECRET_NAMES, REQUIRED_SECRET_NAMES
from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO

RO_HANDLERS = (
    "discover_assets",
    "describe_asset",
    "detect_schema_drift",
    "profile_dataset",
    "sample_dataset",
    "infer_relationships",
    "validate_query",
    "execute_query",
    "get_execution_metrics",
    "get_cost_metrics",
)
DEV_HANDLERS = ("create_dataset", "drop_dataset")


def clear_snowflake_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove Snowflake env vars so fail-closed tests stay valid on a credentialed host."""
    for name in REQUIRED_SECRET_NAMES + OPTIONAL_SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)


def make_context(
    *,
    deadline_seconds: int = 30,
    workflow_id: UUID | None = None,
    operation_idempotency_key: str | None = None,
    attempt_number: int = 1,
) -> CallContext:
    now = datetime.now(UTC)
    return CallContext(
        workflow_id=workflow_id or uuid4(),
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key=operation_idempotency_key or "a" * 64,
        resolved_input_digest="b" * 64,
        contract_snapshot_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=attempt_number,
        claim_epoch=1,
        cancellation_epoch=0,
        deadline=now + timedelta(seconds=deadline_seconds),
        external_correlation="corr",
        redaction=RedactionPolicy(),
    )


@pytest.fixture
def fake_ro() -> FakeSnowflakeConnector:
    return FakeSnowflakeConnector(FAKE_SNOWFLAKE_RO)


@pytest.fixture
def fake_dev() -> FakeSnowflakeConnector:
    return FakeSnowflakeConnector(FAKE_SNOWFLAKE_DEV)


@pytest.fixture
def fake_pair() -> tuple[FakeSnowflakeConnector, FakeSnowflakeConnector]:
    return build_fake_pair()
