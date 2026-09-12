"""Composition root for the DE 002C offline slice."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.events import EventBus
from aide.app.slice import OfflineSliceService, classify_sql_handler
from aide.capabilities.io import (
    CreateDatasetInput,
    DescribeAssetInput,
    DiscoverAssetsInput,
    ExecuteQueryInput,
    GenerateSqlQueryInput,
    InterpretRequirementInput,
    PlanPhaseInput,
    SelectRelevantAssetsInput,
    ValidateQueryInput,
)
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.context import CallContext, RedactionPolicy
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO
from aide.llm.gateway import LlmGateway
from aide.persistence.database import create_engine, create_session_factory
from aide.policy.engine import PolicyEngine
from aide.reasoning.capabilities import ReasoningCapabilities
from aide.tools.registry import ToolRegistry


def build_offline_stack(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    snowflake_ro: FakeSnowflakeConnector | None = None,
    snowflake_dev: FakeSnowflakeConnector | None = None,
) -> OfflineSliceService:
    capabilities = kernel_registry()
    connectors = ConnectorRegistry()
    connectors.register(FAKE_SNOWFLAKE_RO, capabilities.required_permissions())
    connectors.register(FAKE_SNOWFLAKE_DEV, capabilities.required_permissions())
    ro, dev = (snowflake_ro, snowflake_dev) if snowflake_ro and snowflake_dev else build_fake_pair()
    reasoner = ReasoningCapabilities(LlmGateway())
    tools = ToolRegistry(capabilities=capabilities, connectors=connectors, policy=PolicyEngine())
    events = EventBus()

    def call_context(context: dict[str, Any]) -> CallContext:
        return CallContext(
            workflow_id=_uuid(context["workflow_id"]),
            phase_run_id=_uuid(context["phase_run_id"]),
            task_id=_uuid(context["task_id"]),
            operation_idempotency_key=context["operation_idempotency_key"],
            resolved_input_digest=context["resolved_input_digest"],
            contract_snapshot_id=_uuid(context["contract_snapshot_id"]),
            attempt_id=_uuid(context["attempt_id"]),
            attempt_number=int(context.get("attempt_number", 1)),
            claim_epoch=int(context.get("claim_epoch", 1)),
            cancellation_epoch=0,
            deadline=datetime.now(UTC) + timedelta(seconds=30),
            external_correlation=context["operation_idempotency_key"],
            redaction=RedactionPolicy(),
        )

    async def discover(payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, DiscoverAssetsInput)
        return await ro.discover_assets(payload, call_context(context))

    async def describe(payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, DescribeAssetInput)
        return await ro.describe_asset(payload, call_context(context))

    async def validate(payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, ValidateQueryInput)
        return await ro.validate_query(payload, call_context(context))

    async def execute(payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, ExecuteQueryInput)
        return await ro.execute_query(payload, call_context(context))

    async def create(payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, CreateDatasetInput)
        return await dev.create_dataset(payload, call_context(context))

    async def classify(payload: BaseModel, context: dict[str, Any]) -> BaseModel:
        return classify_sql_handler(payload, context)

    async def interpret(payload: BaseModel, _context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, InterpretRequirementInput)
        return reasoner.interpret_requirement(payload)

    async def plan(payload: BaseModel, _context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, PlanPhaseInput)
        return reasoner.plan_phase(payload)

    async def select(payload: BaseModel, _context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, SelectRelevantAssetsInput)
        return reasoner.select_relevant_assets(payload)

    async def generate(payload: BaseModel, _context: dict[str, Any]) -> BaseModel:
        assert isinstance(payload, GenerateSqlQueryInput)
        return reasoner.generate_sql_query(payload)

    tools.register("discover_assets", discover)
    tools.register("describe_asset", describe)
    tools.register("validate_query", validate)
    tools.register("execute_query", execute)
    tools.register("create_dataset", create)
    tools.register("classify_sql", classify)
    tools.register("interpret_requirement", interpret)
    tools.register("plan_phase", plan)
    tools.register("select_relevant_assets", select)
    tools.register("generate_sql_query", generate)
    service = OfflineSliceService(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        tools=tools,
        reasoner=reasoner,
        snowflake_ro=ro,
        snowflake_dev=dev,
        events=events,
    )
    return service


def session_factory_from_url(database_url: str) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(create_engine(database_url))


def _uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
