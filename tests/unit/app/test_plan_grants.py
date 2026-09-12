from __future__ import annotations

import pytest

from aide.app.plan_validation import PlanValidationError, validate_plan
from aide.capabilities.io import Plan, PlannedTask
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState


def test_read_only_plan_rejects_development_write_before_materialization() -> None:
    capabilities = kernel_registry()
    connectors = ConnectorRegistry()
    connectors.register(SNOWFLAKE_RO, capabilities.required_permissions())
    connectors.register(SNOWFLAKE_DEV, capabilities.required_permissions())
    plan = Plan(
        phase=WorkflowState.EXECUTION,
        tasks=(
            PlannedTask(
                local_id="write-1",
                capability_id="create_dataset",
                connector_id="snowflake_dev",
                depends_on=(),
                inputs={
                    "target": {
                        "connector_id": "snowflake_dev",
                        "address": ["AIDE_DEV", "PUBLIC", "ORDERS"],
                        "kind": "TABLE",
                    },
                    "definition": {"dialect": "snowflake", "text": "SELECT 1 AS id"},
                    "replace": False,
                },
                rationale="write should not be planned under READ grants",
            ),
        ),
        phase_exit_criteria=("created",),
    )
    with pytest.raises(PlanValidationError, match="DEVELOPMENT_WRITE"):
        validate_plan(
            plan,
            capabilities=capabilities,
            connectors=connectors,
            effective_grants=frozenset({PermissionLevel.READ}),
        )


def test_development_write_plan_is_accepted_when_grant_is_effective() -> None:
    capabilities = kernel_registry()
    connectors = ConnectorRegistry()
    connectors.register(SNOWFLAKE_RO, capabilities.required_permissions())
    connectors.register(SNOWFLAKE_DEV, capabilities.required_permissions())
    plan = Plan(
        phase=WorkflowState.EXECUTION,
        tasks=(
            PlannedTask(
                local_id="write-1",
                capability_id="create_dataset",
                connector_id="snowflake_dev",
                depends_on=(),
                inputs={
                    "target": {
                        "connector_id": "snowflake_dev",
                        "address": ["AIDE_DEV", "PUBLIC", "ORDERS"],
                        "kind": "TABLE",
                    },
                    "definition": {"dialect": "snowflake", "text": "SELECT 1 AS id"},
                    "replace": False,
                },
                rationale="authorized write",
            ),
        ),
        phase_exit_criteria=("created",),
    )
    templates = validate_plan(
        plan,
        capabilities=capabilities,
        connectors=connectors,
        effective_grants=frozenset({PermissionLevel.READ, PermissionLevel.DEVELOPMENT_WRITE}),
    )
    assert [item.capability_id for item in templates] == ["create_dataset"]
