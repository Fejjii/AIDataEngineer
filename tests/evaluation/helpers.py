"""Shared Interview MVP evaluation helpers. Test-only; no product architecture change."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.interview import build_interview_stack
from aide.app.supervisor import InterviewSupervisor
from aide.connectors.base.context import CallContext, RedactionPolicy
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.dbt.errors import DbtMappedError
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.domain.failures import FailureClass


class NthFailDbt(FakeDbtConnector):
    """Fail the Nth invocation of selected dbt capabilities. Evaluation injection only."""

    def __init__(
        self,
        spec: ConnectorSpec | None = None,
        *,
        work_root: Path,
        fail_on: dict[str, int] | None = None,
        failure: FailureClass = FailureClass.CONNECTOR_FAILURE,
    ) -> None:
        super().__init__(spec, work_root=work_root)
        self._eval_counts: dict[str, int] = {}
        self._fail_on = fail_on or {}
        self._eval_failure = failure

    def _maybe_fail(self, capability: str) -> None:
        self._eval_counts[capability] = self._eval_counts.get(capability, 0) + 1
        if self._fail_on.get(capability) == self._eval_counts[capability]:
            raise DbtMappedError(self._eval_failure, f"injected {self._eval_failure.value}")
        super()._maybe_fail(capability)


def make_call_context(*, workflow_id: UUID | None = None) -> CallContext:
    now = datetime.now(UTC)
    return CallContext(
        workflow_id=workflow_id or uuid4(),
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key="a" * 64,
        resolved_input_digest="b" * 64,
        contract_snapshot_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        claim_epoch=1,
        cancellation_epoch=0,
        deadline=now + timedelta(seconds=30),
        external_correlation="eval",
        redaction=RedactionPolicy(),
    )


def build_eval_stack(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    snowflake_ro: FakeSnowflakeConnector | None = None,
    snowflake_dev: FakeSnowflakeConnector | None = None,
    dbt: FakeDbtConnector | None = None,
) -> tuple[InterviewSupervisor, FakeSnowflakeConnector, FakeSnowflakeConnector, FakeDbtConnector]:
    ro = snowflake_ro
    dev = snowflake_dev
    if ro is None or dev is None:
        built_ro, built_dev = build_fake_pair()
        if ro is None:
            ro = built_ro
        if dev is None:
            dev = built_dev
    dbt_connector = dbt or FakeDbtConnector(work_root=tmp_path)
    supervisor = build_interview_stack(
        session_factory,
        work_root=tmp_path,
        snowflake_ro=ro,
        snowflake_dev=dev,
        dbt=dbt_connector,
    )
    return supervisor, ro, dev, dbt_connector
