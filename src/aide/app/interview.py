"""Composition root for the Interview MVP Supervisor and Governed Tool Gateway.

This module may import vendor fake and real connectors. Application services,
capability groups, and orchestration must not.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.events import EventBus
from aide.app.gateway import GovernedToolGateway
from aide.app.supervisor import (
    InterviewResult,
    InterviewSupervisor,
    generate_transformation_handler,
    plan_phase_handler,
    propose_model_design_handler,
    propose_repair_handler,
    validate_repair_handler,
)
from aide.capabilities.io import LoadManifestSourcesInput
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.real import RealDbtConnector, build_real_snowflake
from aide.connectors.dbt.specs import DBT_DEV, FAKE_DBT_DEV
from aide.connectors.snowflake.fake import FakeSnowflakeConnector, build_fake_pair
from aide.connectors.snowflake.live_probe import (
    LiveProbeReport,
    drop_workflow_dev_schemas,
    run_live_interview_smoke,
)
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.connectors.snowflake.specs import FAKE_SNOWFLAKE_DEV, FAKE_SNOWFLAKE_RO
from aide.domain.artifacts import ExecutionMode
from aide.domain.benchmark import INTERVIEW_REQUEST, LiveSmokeStatus
from aide.domain.enums import TargetEnv
from aide.persistence.gateway import GatewayDispatchRepository
from aide.persistence.repositories import ArtifactRepository
from aide.policy.engine import PolicyEngine
from aide.profiling.offline import bind_vantara_fixtures
from aide.tools.binding import AttributeConnectorBinding, LocalHandlerBinding

ReconcileValue = EffectFound | NoEffect | InProgress | Unknown
_PROD_TOKENS = frozenset({"PROD", "PRODUCTION", "STAGING"})
_REQUIRED_LIVE_CONNECTORS = frozenset({"snowflake_ro", "snowflake_dev", "dbt_dev"})


@runtime_checkable
class _LoadCapable(Protocol):
    async def health(self) -> ConnectorHealthSnapshot | None: ...

    async def load_manifest_sources(
        self, payload: LoadManifestSourcesInput, context: CallContext
    ) -> BaseModel: ...

    async def reconcile(self, recovery: RecoveryContext) -> ReconcileValue: ...


class ManifestDualLoadBinding:
    """One gateway operation: Snowflake DEV CSV load plus optional local dbt sources."""

    spec: ConnectorSpec | None

    def __init__(
        self,
        snowflake_dev: _LoadCapable,
        dbt: object,
        spec: ConnectorSpec,
        *,
        materialize_local_sources: bool = True,
    ) -> None:
        self._snowflake = snowflake_dev
        self._dbt = dbt
        self.spec = spec
        self._materialize_local_sources = materialize_local_sources

    async def health(self) -> ConnectorHealthSnapshot | None:
        snapshot = await self._snowflake.health()
        assert isinstance(snapshot, ConnectorHealthSnapshot)
        return snapshot

    async def execute(
        self, capability_id: str, payload: BaseModel, context: CallContext
    ) -> BaseModel:
        del capability_id
        typed = LoadManifestSourcesInput.model_validate(payload)
        if self._materialize_local_sources:
            ensure = getattr(self._dbt, "ensure_workflow_sources", None)
            if ensure is not None:
                ensure(typed, context)
        result = await self._snowflake.load_manifest_sources(typed, context)
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
        result = await self._snowflake.reconcile(recovery)
        if not isinstance(result, (EffectFound, NoEffect, InProgress, Unknown)):
            raise TypeError("connector reconcile returned an untyped result")
        return result


class InvoiceStatusDriftInjector:
    """Composition-root injector for the accepted INVOICE_STATUS → STATUS rename."""

    def __init__(self, snowflake_ro: FakeSnowflakeConnector, dbt: FakeDbtConnector) -> None:
        self._snowflake_ro = snowflake_ro
        self._dbt = dbt

    def inject_invoice_status_rename(self, workflow_id: UUID) -> None:
        self._snowflake_ro.rename_column(
            ("VANTARA_RAW", "BILLING", "INVOICES"), "INVOICE_STATUS", "STATUS"
        )
        self._dbt.rename_loaded_column(
            workflow_id, "BILLING", "INVOICES", "INVOICE_STATUS", "STATUS"
        )


def _register_local_handlers(gateway: GovernedToolGateway) -> None:
    async def plan(payload: BaseModel, context: CallContext) -> BaseModel:
        return plan_phase_handler(payload, context)

    async def generate(payload: BaseModel, context: CallContext) -> BaseModel:
        return generate_transformation_handler(payload, context)

    async def propose(payload: BaseModel, context: CallContext) -> BaseModel:
        return propose_model_design_handler(payload, context)

    async def propose_repair(payload: BaseModel, context: CallContext) -> BaseModel:
        return propose_repair_handler(payload, context)

    async def validate_repair(payload: BaseModel, context: CallContext) -> BaseModel:
        return validate_repair_handler(payload, context)

    gateway.register_binding("plan_phase", LocalHandlerBinding(plan))
    gateway.register_binding("generate_transformation", LocalHandlerBinding(generate))
    gateway.register_binding("propose_model_design", LocalHandlerBinding(propose))
    gateway.register_binding("propose_repair", LocalHandlerBinding(propose_repair))
    gateway.register_binding("validate_repair", LocalHandlerBinding(validate_repair))


def _bind_interview_connectors(
    gateway: GovernedToolGateway,
    *,
    snowflake_ro: object,
    snowflake_dev: _LoadCapable,
    dbt: object,
    ro_spec: ConnectorSpec,
    dev_spec: ConnectorSpec,
    dbt_spec: ConnectorSpec,
    materialize_local_sources: bool,
) -> None:
    ro_binding = AttributeConnectorBinding(snowflake_ro, ro_spec)
    dbt_binding = AttributeConnectorBinding(dbt, dbt_spec)
    load_binding = ManifestDualLoadBinding(
        snowflake_dev,
        dbt,
        dev_spec,
        materialize_local_sources=materialize_local_sources,
    )
    for capability_id in (
        "discover_assets",
        "describe_asset",
        "detect_schema_drift",
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
    _register_local_handlers(gateway)


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
    _bind_interview_connectors(
        gateway,
        snowflake_ro=snowflake_ro,
        snowflake_dev=snowflake_dev,
        dbt=dbt_connector,
        ro_spec=FAKE_SNOWFLAKE_RO,
        dev_spec=FAKE_SNOWFLAKE_DEV,
        dbt_spec=FAKE_DBT_DEV,
        materialize_local_sources=True,
    )
    return InterviewSupervisor(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        gateway=gateway,
        events=EventBus(),
        execution_mode=ExecutionMode.MOCK,
        drift_injector=InvoiceStatusDriftInjector(snowflake_ro, dbt_connector),
    )


def build_live_interview_stack(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    work_root: Path,
    snowflake_ro: RealSnowflakeConnector | None = None,
    snowflake_dev: RealSnowflakeConnector | None = None,
    dbt: RealDbtConnector | None = None,
) -> InterviewSupervisor:
    """Governed live composition: real Snowflake RO/DEV and real dbt Snowflake."""
    capabilities = kernel_registry()
    connectors = ConnectorRegistry()
    required = capabilities.required_permissions()
    connectors.register(SNOWFLAKE_RO, required)
    connectors.register(SNOWFLAKE_DEV, required)
    connectors.register(DBT_DEV, required)
    work_root.mkdir(parents=True, exist_ok=True)
    ro = snowflake_ro or RealSnowflakeConnector(SNOWFLAKE_RO)
    dev = snowflake_dev or RealSnowflakeConnector(SNOWFLAKE_DEV)
    dbt_connector = dbt or build_real_snowflake(work_root, timeout_seconds=300)
    gateway = GovernedToolGateway(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        policy=PolicyEngine(),
        execution_mode=ExecutionMode.REAL,
    )
    _bind_interview_connectors(
        gateway,
        snowflake_ro=ro,
        snowflake_dev=dev,
        dbt=dbt_connector,
        ro_spec=SNOWFLAKE_RO,
        dev_spec=SNOWFLAKE_DEV,
        dbt_spec=DBT_DEV,
        materialize_local_sources=False,
    )
    return InterviewSupervisor(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        gateway=gateway,
        events=EventBus(),
        execution_mode=ExecutionMode.REAL,
        drift_injector=None,
    )


def _live_connectors_are_dev_only() -> bool:
    if SNOWFLAKE_RO.target_environment is not TargetEnv.DEV:
        return False
    if SNOWFLAKE_DEV.target_environment is not TargetEnv.DEV:
        return False
    if DBT_DEV.target_environment is not TargetEnv.DEV:
        return False
    names = (
        SNOWFLAKE_RO.allow_list.databases
        | SNOWFLAKE_DEV.allow_list.databases
        | DBT_DEV.allow_list.databases
    )
    return not any(name.upper() in _PROD_TOKENS for name in names)


def _policy_allows(intent: object) -> bool:
    decision = getattr(intent, "policy_decision", None)
    if not isinstance(decision, dict):
        return False
    outcome = str(decision.get("decision") or "").upper()
    return outcome == "ALLOW"


def _policy_mentions_prod_or_staging(intent: object) -> bool:
    decision = getattr(intent, "policy_decision", None)
    blob = str(decision or "").upper()
    return any(token in blob for token in _PROD_TOKENS)


async def _assess_governed_live(
    session_factory: async_sessionmaker[AsyncSession],
    result: InterviewResult,
) -> tuple[bool, str, dict[str, Any]]:
    async with session_factory() as session:
        intents = await GatewayDispatchRepository(session).list_for_workflow(result.workflow_id)
        artifacts = await ArtifactRepository(session).list_for_workflow(result.workflow_id)
    connector_ids = tuple(sorted({str(item.connector_id) for item in intents if item.connector_id}))
    missing = _REQUIRED_LIVE_CONNECTORS.difference(connector_ids)
    policy_ok = bool(intents) and all(_policy_allows(item) for item in intents)
    prod = any(_policy_mentions_prod_or_staging(item) for item in intents)
    evidence_ok = any(row.body is not None for row in artifacts)
    tests_ok = bool(result.tests_ok)
    quality_ok = bool(result.quality is not None and result.quality.passed)
    execute_ok = bool(result.execute_ok)
    failed = bool(result.failed or result.blocked or result.parked)
    passed = (
        not failed
        and not missing
        and policy_ok
        and not prod
        and evidence_ok
        and tests_ok
        and quality_ok
        and execute_ok
        and _live_connectors_are_dev_only()
    )
    if missing:
        detail = f"gateway did not dispatch required connectors: {sorted(missing)}"
    elif not policy_ok:
        detail = "gateway dispatch is missing ALLOW policy decisions"
    elif prod:
        detail = "policy decision referenced production or staging"
    elif not evidence_ok:
        detail = "governed live path did not persist evidence artifacts"
    elif failed:
        detail = (
            result.fail_reason or result.block_reason or result.park_reason or "live run failed"
        )
    elif not execute_ok:
        detail = "live governed execute_transformation did not succeed"
    elif not tests_ok:
        detail = "live governed dbt tests did not succeed"
    elif not quality_ok:
        detail = "live governed quality assertions did not succeed"
    else:
        detail = (
            "governed Supervisor/Tool Gateway path exercised real Snowflake RO/DEV "
            "and real dbt without mutating VANTARA_RAW"
        )
    return (
        passed,
        detail,
        {
            "connector_ids": connector_ids,
            "policy_ok": policy_ok,
            "evidence_ok": evidence_ok,
            "tests_ok": tests_ok,
            "quality_ok": quality_ok,
            "dev_only": _live_connectors_are_dev_only() and not prod,
        },
    )


async def run_governed_live_interview(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    work_root: Path,
) -> tuple[InterviewResult | None, bool, str, dict[str, Any]]:
    """Run the strongest RAW-safe live Interview path through the gateway."""
    work_root.mkdir(parents=True, exist_ok=True)
    snowflake_ro = RealSnowflakeConnector(SNOWFLAKE_RO)
    snowflake_dev = RealSnowflakeConnector(SNOWFLAKE_DEV)
    dbt = build_real_snowflake(work_root, timeout_seconds=300)
    supervisor = build_live_interview_stack(
        session_factory,
        work_root=work_root,
        snowflake_ro=snowflake_ro,
        snowflake_dev=snowflake_dev,
        dbt=dbt,
    )
    result: InterviewResult | None = None
    try:
        result = await supervisor.run_customer_revenue(
            INTERVIEW_REQUEST,
            include_schema_drift=False,
        )
        passed, detail, meta = await _assess_governed_live(session_factory, result)
        return result, passed, detail, meta
    except Exception as exc:
        return result, False, str(exc)[:400], {}
    finally:
        await snowflake_ro.close()
        await snowflake_dev.close()
        await dbt.close()
        if result is not None:
            await drop_workflow_dev_schemas(result.workflow_id)


async def run_credentialed_live_interview_smoke(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    *,
    work_root: Path | None = None,
) -> LiveProbeReport:
    """AT-18/AT-19 grant probe plus AT-24 governed real-connector Interview path."""
    probe = await run_live_interview_smoke()
    if probe.status is not LiveSmokeStatus.PASSED:
        return probe
    if session_factory is None:
        return probe.model_copy(
            update={
                "status": LiveSmokeStatus.FAILED,
                "detail": ("governed live Interview path requires a control-plane session factory"),
            }
        )
    root = work_root or Path(tempfile.mkdtemp(prefix="aide-live-interview-"))
    _result, passed, detail, meta = await run_governed_live_interview(
        session_factory, work_root=root
    )
    combined = probe.status is LiveSmokeStatus.PASSED and passed
    return probe.model_copy(
        update={
            "status": LiveSmokeStatus.PASSED if combined else LiveSmokeStatus.FAILED,
            "governed_path_exercised": True,
            "gateway_connector_ids": tuple(meta.get("connector_ids") or ()),
            "policy_evaluated": bool(meta.get("policy_ok")),
            "evidence_persisted": bool(meta.get("evidence_ok")),
            "dev_only_execution": bool(meta.get("dev_only")),
            "independent_verifier_ran": False,
            "tests_ok": bool(meta.get("tests_ok")),
            "quality_ok": bool(meta.get("quality_ok")),
            "include_schema_drift": False,
            "production_or_staging_action": False,
            "grant_sql_executed": False,
            "detail": f"{probe.detail}; {detail}" if combined else detail,
        }
    )
