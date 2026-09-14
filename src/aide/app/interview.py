"""Composition root for the Interview MVP Supervisor and Governed Tool Gateway.

This module may import vendor fake connectors. Application services, capability
groups, and orchestration must not.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.events import EventBus
from aide.app.gateway import GovernedToolGateway
from aide.app.supervisor import (
    InterviewSupervisor,
    generate_transformation_handler,
    plan_phase_handler,
    propose_model_design_handler,
)
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.specs import FAKE_DBT_DEV
from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO
from aide.domain.artifacts import ExecutionMode
from aide.policy.engine import PolicyEngine
from aide.profiling.offline import bind_vantara_fixtures
from aide.tools.binding import AttributeConnectorBinding, LocalHandlerBinding

ReconcileValue = EffectFound | NoEffect | InProgress | Unknown


class ManifestDualLoadBinding:
    """One gateway operation: Snowflake DEV CSV load plus dbt workspace source load."""

    def __init__(self, snowflake_dev: object, dbt: FakeDbtConnector, spec: ConnectorSpec) -> None:
        self._snowflake = snowflake_dev
        self._dbt = dbt
        self.spec = spec

    async def health(self) -> ConnectorHealthSnapshot | None:
        health = self._snowflake.health
        snapshot = await health()
        assert isinstance(snapshot, ConnectorHealthSnapshot)
        return snapshot

    async def execute(
        self, capability_id: str, payload: BaseModel, context: CallContext
    ) -> BaseModel:
        del capability_id
        method = self._snowflake.load_manifest_sources
        self._dbt.ensure_workflow_sources(payload, context)
        result = await method(payload, context)
        assert isinstance(result, BaseModel)
        return result

    async def cancel(self, capability_id: str, context: CallContext) -> None:
        del capability_id
        cancel = getattr(self._snowflake, "cancel", None)
        if cancel is None:
            return None
        await cancel(context)
        return None

    async def reconcile(self, recovery: RecoveryContext) -> ReconcileValue:
        reconcile = self._snowflake.reconcile
        result = await reconcile(recovery)
        if not isinstance(result, (EffectFound, NoEffect, InProgress, Unknown)):
            raise TypeError("connector reconcile returned an untyped result")
        return result


def build_interview_stack(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    work_root: Path,
    snowflake_ro: FakeSnowflakeConnector | None = None,
    snowflake_dev: FakeSnowflakeConnector | None = None,
    dbt: FakeDbtConnector | None = None,
    fixture_version: str = "v1",
) -> InterviewSupervisor:
    capabilities = kernel_registry()
    connectors = ConnectorRegistry()
    required = capabilities.required_permissions()
    connectors.register(FAKE_SNOWFLAKE_RO, required)
    connectors.register(FAKE_SNOWFLAKE_DEV, required)
    connectors.register(FAKE_DBT_DEV, required)
    if snowflake_ro is None or snowflake_dev is None:
        snowflake_ro, snowflake_dev = build_fake_pair()
    bind_vantara_fixtures(snowflake_ro, version=fixture_version)
    dbt_connector = dbt or FakeDbtConnector(FAKE_DBT_DEV, work_root=work_root)
    gateway = GovernedToolGateway(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        policy=PolicyEngine(),
        execution_mode=ExecutionMode.MOCK,
    )
    ro_binding = AttributeConnectorBinding(snowflake_ro, FAKE_SNOWFLAKE_RO)
    dbt_binding = AttributeConnectorBinding(dbt_connector, FAKE_DBT_DEV)
    load_binding = ManifestDualLoadBinding(snowflake_dev, dbt_connector, FAKE_SNOWFLAKE_DEV)
    for capability_id in (
        "discover_assets",
        "describe_asset",
        "profile_estate",
        "evaluate_execution_policy",
    ):
        gateway.register_binding(capability_id, ro_binding, connector_id="snowflake_ro")
    gateway.register_binding("load_manifest_sources", load_binding, connector_id="snowflake_dev")
    for capability_id in (
        "create_transformation",
        "parse_transformation",
        "compile_transformation",
        "execute_transformation",
        "run_pipeline",
        "run_tests",
        "validate_interview_quality",
    ):
        gateway.register_binding(capability_id, dbt_binding, connector_id="dbt_dev")

    async def plan(payload: BaseModel, context: CallContext) -> BaseModel:
        return plan_phase_handler(payload, context)

    async def generate(payload: BaseModel, context: CallContext) -> BaseModel:
        return generate_transformation_handler(payload, context)

    async def propose(payload: BaseModel, context: CallContext) -> BaseModel:
        return propose_model_design_handler(payload, context)

    gateway.register_binding("plan_phase", LocalHandlerBinding(plan))
    gateway.register_binding("generate_transformation", LocalHandlerBinding(generate))
    gateway.register_binding("propose_model_design", LocalHandlerBinding(propose))
    return InterviewSupervisor(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        gateway=gateway,
        events=EventBus(),
        execution_mode=ExecutionMode.MOCK,
    )
