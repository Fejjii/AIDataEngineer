from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from aide.domain.enums import RiskLevel, TargetEnv
from aide.domain.identity import (
    UnresolvedInputError,
    compute_operation_idempotency_key,
    compute_resolved_input_digest,
    contains_unresolved_placeholder,
)
from aide.domain.permissions import PermissionLevel
from aide.domain.states import AttemptOutcome, DispatchState
from aide.domain.tasks import TaskAttempt, TaskTemplate, materialize_task


class SampleInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    table: str
    limit: int = 10


def _template(phase_run_id: UUID | None = None) -> TaskTemplate:
    return TaskTemplate(
        template_id=uuid4(),
        phase_run_id=phase_run_id or uuid4(),
        local_id="describe_orders",
        capability_id="describe_asset",
        capability_contract_version=1,
        connector_id="snowflake_ro",
        unresolved_inputs={"asset": {"$from": "discover", "path": "assets.0"}},
        timeout_seconds=60,
        max_attempts=3,
    )


def test_template_has_no_operation_identity() -> None:
    template = _template()
    assert "operation_idempotency_key" not in TaskTemplate.model_fields
    assert contains_unresolved_placeholder(template.unresolved_inputs)


def test_identity_impossible_before_resolved_validated_input() -> None:
    template = _template()
    with pytest.raises(UnresolvedInputError):
        materialize_task(
            template,
            task_id=uuid4(),
            workflow_id=uuid4(),
            resolved_inputs={"asset": {"$from": "discover", "path": "assets.0"}},
            input_schema=SampleInput,
            input_schema_version=1,
            output_schema_version=1,
            connector_id="snowflake_ro",
            connector_version="1.0.0",
            target_environment=TargetEnv.DEV,
            required_permission=PermissionLevel.READ,
            risk=RiskLevel.LOW,
        )
    with pytest.raises(UnresolvedInputError):
        compute_operation_idempotency_key(
            workflow_id=uuid4(),
            phase_run_id=uuid4(),
            local_id="x",
            capability_id="execute_query",
            capability_contract_version=1,
            connector_id="snowflake_ro",
            connector_version="1.0.0",
            target_environment=TargetEnv.DEV,
            resolved_input_digest="",
        )


def test_same_operation_stable_across_attempts() -> None:
    template = _template()
    workflow_id = uuid4()
    task = materialize_task(
        template,
        task_id=uuid4(),
        workflow_id=workflow_id,
        resolved_inputs=SampleInput(table="ORDERS"),
        input_schema=SampleInput,
        input_schema_version=1,
        output_schema_version=1,
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        required_permission=PermissionLevel.READ,
        risk=RiskLevel.LOW,
    )
    attempts = [
        TaskAttempt(
            attempt_id=uuid4(),
            task_id=task.task_id,
            phase_run_id=task.phase_run_id,
            attempt_number=number,
            operation_idempotency_key=task.operation_idempotency_key,
            resolved_input_digest=task.resolved_input_digest,
            lease_owner="worker-1",
            claim_epoch=number,
            cancellation_epoch=0,
            started_at=datetime.now(UTC),
            dispatch_state=DispatchState.DISPATCHED,
            outcome=AttemptOutcome.STARTED,
        )
        for number in (1, 2, 3)
    ]
    assert {item.operation_idempotency_key for item in attempts} == {task.operation_idempotency_key}
    assert attempts[0].attempt_number != attempts[1].attempt_number


def test_distinct_phase_runs_produce_distinct_identity() -> None:
    workflow_id = uuid4()
    first = materialize_task(
        _template(),
        task_id=uuid4(),
        workflow_id=workflow_id,
        resolved_inputs=SampleInput(table="ORDERS"),
        input_schema=SampleInput,
        input_schema_version=1,
        output_schema_version=1,
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        required_permission=PermissionLevel.READ,
        risk=RiskLevel.LOW,
    )
    second = materialize_task(
        _template(),
        task_id=uuid4(),
        workflow_id=workflow_id,
        resolved_inputs=SampleInput(table="ORDERS"),
        input_schema=SampleInput,
        input_schema_version=1,
        output_schema_version=1,
        connector_id="snowflake_ro",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        required_permission=PermissionLevel.READ,
        risk=RiskLevel.LOW,
    )
    assert first.phase_run_id != second.phase_run_id
    assert first.operation_idempotency_key != second.operation_idempotency_key
    assert (
        first.resolved_input_digest
        == second.resolved_input_digest
        == compute_resolved_input_digest(SampleInput(table="ORDERS"))
    )
