"""DE 002C offline safe-SQL slice composition."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.events import EventBus
from aide.app.parking import park_task
from aide.app.plan_validation import validate_plan
from aide.auth.grants import GrantAuthorizer, GrantForgeryError
from aide.auth.session import digest_session_token, issue_session_token
from aide.capabilities.io import (
    Budget,
    ClassifySqlInput,
    ClassifySqlOutput,
    DiscoverAssetsInput,
    DiscoverAssetsOutput,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    GenerateSqlQueryInput,
    GenerateSqlQueryOutput,
    InterpretRequirementInput,
    Plan,
    PlanConstraints,
    PlanPhaseInput,
    RequirementSpec,
    SelectRelevantAssetsInput,
    SelectRelevantAssetsOutput,
    ValidateQueryInput,
    ValidationReport,
)
from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.discovery.catalog import MetadataCatalog
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.enums import TargetEnv
from aide.domain.identity import canonical_json_bytes
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.sql import SqlClassification
from aide.domain.states import TaskState, WorkflowState
from aide.domain.tasks import TaskTemplate
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.orchestration.compatibility import evaluate_pinned_contract
from aide.orchestration.coordination import NextPhase, reduce_and_advance
from aide.orchestration.materialization import (
    TemplateSpec,
    create_phase_occurrence,
    persist_materialized_task,
)
from aide.orchestration.worker import TaskClaim, claim_task, finalize_success, mark_dispatched
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskTemplateModel,
    WorkflowModel,
)
from aide.persistence.repositories import (
    ArtifactRepository,
    ConnectorHealthRepository,
    ContractSnapshotRepository,
    GrantRepository,
    SessionRepository,
    WorkflowRepository,
)
from aide.policy.sql.classifier import classify_sql as classify_sql_pure
from aide.quality.checks import validate_query_result
from aide.reasoning.capabilities import ReasoningCapabilities
from aide.tools.registry import PolicyDenied, PolicyParked, ToolRegistry

OWNER = "de002c-worker"
SLICE_CAPABILITIES = {
    "discover_assets",
    "describe_asset",
    "select_relevant_assets",
    "interpret_requirement",
    "plan_phase",
    "generate_sql_query",
    "classify_sql",
    "validate_query",
    "execute_query",
    "create_dataset",
}


@dataclass
class SliceResult:
    workflow_id: UUID
    principal: PrincipalRef
    grants: GrantAuthorization
    requirement: RequirementSpec | None = None
    enumeration_plan: Plan | None = None
    catalogue: MetadataCatalog | None = None
    description_plan: Plan | None = None
    selection: SelectRelevantAssetsOutput | None = None
    generated_sql: GenerateSqlQueryOutput | None = None
    classification: SqlClassification | None = None
    execution: ExecuteQueryOutput | None = None
    query_tag: str | None = None
    provenance: ArtifactProvenance | None = None
    validation: ValidationReport | None = None
    parked: bool = False
    park_reason: str | None = None
    workflow_state: str = WorkflowState.RECEIVED.value
    events: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


class OfflineSliceService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        capabilities: CapabilityRegistry,
        connectors: ConnectorRegistry,
        tools: ToolRegistry,
        reasoner: ReasoningCapabilities,
        snowflake_ro: FakeSnowflakeConnector,
        snowflake_dev: FakeSnowflakeConnector,
        events: EventBus,
    ) -> None:
        self._sessions = session_factory
        self._capabilities = capabilities
        self._connectors = connectors
        self._tools = tools
        self._reasoner = reasoner
        self._ro = snowflake_ro
        self._dev = snowflake_dev
        self._events = events
        self._authorizer = GrantAuthorizer()

    @property
    def events(self) -> EventBus:
        return self._events

    async def run_offline(
        self,
        requirement_text: str,
        *,
        requested_grants: frozenset[PermissionLevel] | None = None,
        client_supplied_effective: frozenset[PermissionLevel] | None = None,
        connector_unavailable: bool = False,
        pin_unknown_capability: bool = False,
    ) -> SliceResult:
        requested = requested_grants or frozenset({PermissionLevel.READ})
        principal = PrincipalRef(
            principal_id=uuid4(),
            authentication_source="LOCAL_SESSION",
            roles=frozenset({Role.OPERATOR, Role.APPROVER}),
            session_id=uuid4(),
        )
        now = datetime.now(UTC)
        if client_supplied_effective is not None:
            raise GrantForgeryError("client supplied effective grants are not trusted")
        authorization = self._authorizer.authorize(
            principal,
            requested,
            target_environment=TargetEnv.DEV,
            decided_at=_naive(now),
        )
        if connector_unavailable:
            self._ro.force_health("UNAVAILABLE")
        snapshot = self._snapshot(pin_unknown_capability=pin_unknown_capability)
        async with self._sessions() as session, session.begin():
            await SessionRepository(session).add(
                principal=principal,
                opaque_token_digest=digest_session_token(issue_session_token()),
                csrf_token_digest=digest_session_token("csrf"),
                expires_at=_naive(now + timedelta(hours=8)),
            )
            workflow = await WorkflowRepository(session).add(state=WorkflowState.RECEIVED)
            await GrantRepository(session).persist(
                workflow_id=workflow.workflow_id, authorization=authorization
            )
            await ContractSnapshotRepository(session).add(
                workflow_id=workflow.workflow_id, snapshot=snapshot
            )
            health = await self._ro.health()
            await ConnectorHealthRepository(session).add(_persistable_health(health))
            await append_audit_event(
                session,
                workflow_id=workflow.workflow_id,
                event_type="WORKFLOW_CREATED",
                payload={
                    "effective_grants": sorted(item.value for item in authorization.effective),
                    "requested": sorted(item.value for item in authorization.requested),
                },
                actor={
                    "kind": "PRINCIPAL",
                    "principal_id": str(principal.principal_id),
                    "session_id": str(principal.session_id),
                },
            )
        workflow_id = workflow.workflow_id
        self._events.publish(
            workflow_id,
            "workflow.created",
            {"grants": sorted(item.value for item in authorization.effective)},
        )
        result = SliceResult(workflow_id=workflow_id, principal=principal, grants=authorization)
        result.requirement = self._reasoner.interpret_requirement(
            InterpretRequirementInput(text=requirement_text)
        )
        await self._store_artifact(
            workflow_id,
            "RequirementSpec",
            result.requirement.model_dump(mode="json"),
            capability_id="interpret_requirement",
        )
        result.enumeration_plan = self._reasoner.plan_phase(
            PlanPhaseInput(
                workflow_context_ref=str(workflow_id),
                phase=WorkflowState.DISCOVERY,
                contract_snapshot_ref=str(snapshot.snapshot_id),
                capability_catalogue=(),
                constraints=PlanConstraints(
                    max_tasks=50,
                    effective_grants=tuple(sorted(item.value for item in authorization.effective)),
                ),
                occurrence="ENUMERATION",
            )
        )
        enum_templates = validate_plan(
            result.enumeration_plan, capabilities=self._capabilities, connectors=self._connectors
        )
        discovery_id = uuid4()
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, workflow_id)
            assert workflow_row is not None
            await create_phase_occurrence(
                session,
                workflow_id=workflow_id,
                phase_run_id=discovery_id,
                phase=WorkflowState.DISCOVERY,
                expected_workflow_version=workflow_row.version,
                expected_generation=1,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=enum_templates,
                phase_exit_criteria=result.enumeration_plan.phase_exit_criteria,
            )
        self._events.publish(workflow_id, "phase.created", {"phase": "DISCOVERY", "generation": 1})
        if await self._run_phase(result, phase_run_id=discovery_id, snapshot=snapshot):
            return await self._finalize_status(result)
        assert result.catalogue is not None
        sorted_assets = tuple(sorted(result.catalogue.assets, key=lambda item: item.address))
        if result.catalogue.assets != sorted_assets:
            raise RuntimeError("catalogue must be immutably sorted")
        if "asset_selection" in result.enumeration_plan.phase_exit_criteria:
            raise RuntimeError("enumeration exit criteria must be catalogue-only")
        result.description_plan = self._reasoner.plan_phase(
            PlanPhaseInput(
                workflow_context_ref=str(workflow_id),
                phase=WorkflowState.DISCOVERY,
                contract_snapshot_ref=str(snapshot.snapshot_id),
                capability_catalogue=(),
                constraints=PlanConstraints(max_tasks=50),
                occurrence="DESCRIPTION",
                catalogue_snapshot_id=str(result.catalogue.snapshot_id),
            ),
            catalogue_assets=result.catalogue.asset_refs(),
        )
        describe_ids = [
            task.local_id
            for task in result.description_plan.tasks
            if task.capability_id == "describe_asset"
        ]
        if describe_ids != sorted(describe_ids) or len(describe_ids) != len(set(describe_ids)):
            raise RuntimeError("describe tasks must be explicit, deterministic and unique")
        if any(task.capability_id == "describe_asset" for task in result.enumeration_plan.tasks):
            raise RuntimeError("description must not exist before the planning boundary")
        description_id = uuid4()
        await self._advance_via_planning(
            workflow_id,
            snapshot,
            NextPhase(
                phase_run_id=description_id,
                phase=WorkflowState.DISCOVERY,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=validate_plan(
                    result.description_plan,
                    capabilities=self._capabilities,
                    connectors=self._connectors,
                ),
                phase_exit_criteria=result.description_plan.phase_exit_criteria,
            ),
        )
        if await self._run_phase(result, phase_run_id=description_id, snapshot=snapshot):
            return await self._finalize_status(result)
        sql_plan = self._reasoner.plan_phase(
            PlanPhaseInput(
                workflow_context_ref=str(workflow_id),
                phase=WorkflowState.GENERATION,
                contract_snapshot_ref=str(snapshot.snapshot_id),
                capability_catalogue=(),
                constraints=PlanConstraints(max_tasks=50),
                occurrence="SAFE_SQL",
            )
        )
        execution_id = uuid4()
        await self._advance_via_planning(
            workflow_id,
            snapshot,
            NextPhase(
                phase_run_id=execution_id,
                phase=WorkflowState.EXECUTION,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=validate_plan(
                    sql_plan, capabilities=self._capabilities, connectors=self._connectors
                ),
                phase_exit_criteria=sql_plan.phase_exit_criteria,
            ),
        )
        if await self._run_phase(result, phase_run_id=execution_id, snapshot=snapshot):
            return await self._finalize_status(result)
        if result.execution is None or result.generated_sql is None:
            raise RuntimeError("execution produced no validated output")
        result.validation = validate_query_result(
            result.execution, expected_columns=result.generated_sql.expected_columns
        )
        if not result.validation.passed:
            raise RuntimeError("deterministic validation failed")
        await self._store_artifact(
            workflow_id,
            "ValidationReport",
            result.validation.model_dump(mode="json"),
            capability_id="validate_query",
        )
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, workflow_id)
            assert workflow_row is not None
            workflow_row.state = WorkflowState.COMPLETED.value
            workflow_row.finished_at = _naive(datetime.now(UTC))
            workflow_row.version += 1
        return await self._finalize_status(result)

    async def _advance_via_planning(
        self, workflow_id: UUID, snapshot: ContractSnapshot, target: NextPhase
    ) -> None:
        planning_id = uuid4()
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, workflow_id)
            assert workflow_row is not None
            phase_run = await session.get(PhaseRunModel, workflow_row.active_phase_run_id)
            assert phase_run is not None
            await reduce_and_advance(
                session,
                workflow_id=workflow_id,
                expected_workflow_version=workflow_row.version,
                expected_generation=phase_run.generation,
                next_phase=NextPhase(
                    phase_run_id=planning_id,
                    phase=WorkflowState.PLANNING,
                    contract_snapshot_id=snapshot.snapshot_id,
                    templates=_planning_templates(workflow_id, snapshot.snapshot_id),
                    phase_exit_criteria=("planning_boundary",),
                ),
            )
        async with self._sessions() as session, session.begin():
            await self._complete_control_phase(session, planning_id)
            workflow_row = await session.get(WorkflowModel, workflow_id)
            assert workflow_row is not None
            phase_run = await session.get(PhaseRunModel, planning_id)
            assert phase_run is not None
            await reduce_and_advance(
                session,
                workflow_id=workflow_id,
                expected_workflow_version=workflow_row.version,
                expected_generation=phase_run.generation,
                next_phase=target,
            )

    async def _complete_control_phase(self, session: AsyncSession, phase_run_id: UUID) -> None:
        templates = (
            await session.scalars(
                select(TaskTemplateModel).where(TaskTemplateModel.phase_run_id == phase_run_id)
            )
        ).all()
        phase = await session.get(PhaseRunModel, phase_run_id)
        assert phase is not None
        for template_row in templates:
            spec = self._capabilities.get(template_row.capability_id, 1)
            payload = spec.input_schema.model_validate(template_row.unresolved_inputs)
            template = TaskTemplate(
                template_id=template_row.template_id,
                phase_run_id=phase_run_id,
                local_id=template_row.local_id,
                capability_id=template_row.capability_id,
                capability_contract_version=1,
                connector_id=None,
                unresolved_inputs=template_row.unresolved_inputs,
                timeout_seconds=template_row.timeout_seconds,
                max_attempts=template_row.max_attempts,
            )
            await persist_materialized_task(
                session,
                template=template,
                task_id=uuid4(),
                workflow_id=phase.workflow_id,
                resolved_inputs=payload,
                input_schema=spec.input_schema,
                input_schema_version=1,
                output_schema_version=1,
                connector_id=None,
                connector_version=None,
                target_environment=TargetEnv.DEV,
                required_permission=spec.required_permission,
                risk=spec.risk,
            )
        await session.execute(
            update(MaterializedTaskModel)
            .where(MaterializedTaskModel.phase_run_id == phase_run_id)
            .values(
                status=TaskState.SUCCEEDED.value,
                outputs={"accepted": True},
                output_digest="a" * 64,
            )
        )

    async def _run_phase(
        self, result: SliceResult, *, phase_run_id: UUID, snapshot: ContractSnapshot
    ) -> bool:
        while True:
            await self._materialize_ready(result, phase_run_id=phase_run_id, snapshot=snapshot)
            async with self._sessions() as session, session.begin():
                claim = await claim_task(
                    session,
                    owner=OWNER,
                    now=_naive(datetime.now(UTC)),
                    lease_duration=timedelta(seconds=30),
                )
            if claim is None:
                async with self._sessions() as session:
                    parked_rows = (
                        await session.scalars(
                            select(MaterializedTaskModel).where(
                                MaterializedTaskModel.phase_run_id == phase_run_id,
                                MaterializedTaskModel.status == TaskState.PARKED.value,
                            )
                        )
                    ).all()
                    remaining = (
                        await session.scalars(
                            select(MaterializedTaskModel).where(
                                MaterializedTaskModel.phase_run_id == phase_run_id,
                                MaterializedTaskModel.status.in_(
                                    [
                                        TaskState.READY.value,
                                        TaskState.CLAIMED.value,
                                        TaskState.RUNNING.value,
                                    ]
                                ),
                            )
                        )
                    ).all()
                if parked_rows:
                    result.parked = True
                    result.park_reason = parked_rows[0].disposition_reason
                    return True
                if remaining:
                    continue
                return False
            if await self._execute_claim(result, claim, snapshot):
                return True

    async def _execute_claim(
        self, result: SliceResult, claim: TaskClaim, snapshot: ContractSnapshot
    ) -> bool:
        async with self._sessions() as session, session.begin():
            if any(
                item.capability_id == "missing_capability" for item in snapshot.capability_contracts
            ):
                ok = await evaluate_pinned_contract(
                    session,
                    task_id=claim.task_id,
                    capabilities=self._capabilities,
                    connectors=self._connectors,
                )
                if not ok:
                    result.parked = True
                    result.park_reason = "CONTRACT_VERSION_UNAVAILABLE"
                    return True
            task = await session.get(MaterializedTaskModel, claim.task_id)
            assert task is not None
            await mark_dispatched(session, claim)
            health = await self._ro.health() if task.connector_id == "snowflake_ro" else None
            if task.connector_id == "snowflake_dev":
                health = await self._dev.health()
            context = {
                "workflow_id": task.workflow_id,
                "phase_run_id": task.phase_run_id,
                "task_id": task.task_id,
                "operation_idempotency_key": task.operation_idempotency_key,
                "resolved_input_digest": task.resolved_input_digest,
                "contract_snapshot_id": snapshot.snapshot_id,
                "attempt_id": claim.attempt_id,
                "attempt_number": claim.attempt_number,
                "claim_epoch": claim.claim_epoch,
            }
            try:
                output, _decision = await self._tools.invoke(
                    session,
                    capability_id=task.capability_id,
                    payload=task.resolved_inputs,
                    context=context,
                    principal=result.principal,
                    authorization=result.grants,
                    connector_id=task.connector_id,
                    connector_health=health,
                    sql_classification=result.classification,
                )
            except PolicyParked as exc:
                reason = exc.decision.reasons[0].value if exc.decision.reasons else "PARKED"
                await park_task(
                    session, task_id=task.task_id, reason=reason, now=_naive(datetime.now(UTC))
                )
                result.parked = True
                result.park_reason = reason
                return True
            except PolicyDenied as exc:
                reason = exc.decision.reasons[0].value if exc.decision.reasons else "DENIED"
                await park_task(
                    session, task_id=task.task_id, reason=reason, now=_naive(datetime.now(UTC))
                )
                task.status = TaskState.FAILED.value
                raise
            dumped = output.model_dump(mode="json")
            ok = await finalize_success(
                session, claim=claim, output=dumped, now=_naive(datetime.now(UTC))
            )
            if not ok:
                raise RuntimeError("ambiguous success cannot pass without validated output")
            self._absorb(result, task.capability_id, output, task)
        return False

    async def _materialize_ready(
        self, result: SliceResult, *, phase_run_id: UUID, snapshot: ContractSnapshot
    ) -> None:
        del snapshot
        async with self._sessions() as session, session.begin():
            templates = (
                await session.scalars(
                    select(TaskTemplateModel)
                    .where(TaskTemplateModel.phase_run_id == phase_run_id)
                    .order_by(TaskTemplateModel.local_id)
                )
            ).all()
            tasks = (
                await session.scalars(
                    select(MaterializedTaskModel).where(
                        MaterializedTaskModel.phase_run_id == phase_run_id
                    )
                )
            ).all()
            succeeded = {
                item.local_id for item in tasks if item.status == TaskState.SUCCEEDED.value
            }
            existing = {item.local_id for item in tasks}
            for template_row in templates:
                if template_row.local_id in existing:
                    continue
                if not set(template_row.depends_on).issubset(succeeded):
                    continue
                spec = self._capabilities.get(template_row.capability_id, 1)
                payload = self._resolved_payload(
                    result, template_row.capability_id, template_row.unresolved_inputs
                )
                validated = spec.input_schema.model_validate(payload)
                connector = (
                    self._connectors.get(template_row.connector_id)
                    if template_row.connector_id
                    else None
                )
                template = TaskTemplate(
                    template_id=template_row.template_id,
                    phase_run_id=phase_run_id,
                    local_id=template_row.local_id,
                    capability_id=template_row.capability_id,
                    capability_contract_version=template_row.capability_contract_version,
                    connector_id=template_row.connector_id,
                    unresolved_inputs=payload,
                    timeout_seconds=template_row.timeout_seconds,
                    max_attempts=template_row.max_attempts,
                )
                await persist_materialized_task(
                    session,
                    template=template,
                    task_id=uuid4(),
                    workflow_id=result.workflow_id,
                    resolved_inputs=validated,
                    input_schema=spec.input_schema,
                    input_schema_version=1,
                    output_schema_version=1,
                    connector_id=template_row.connector_id,
                    connector_version=connector.version if connector else None,
                    target_environment=TargetEnv.DEV,
                    required_permission=spec.required_permission,
                    risk=spec.risk,
                )

    def _resolved_payload(
        self, result: SliceResult, capability_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        if capability_id == "discover_assets":
            if raw.get("scope"):
                return raw
            return DiscoverAssetsInput.model_validate(
                {"scope": {"databases": ["RAW", "AIDE_DEV"], "include_views": False}}
            ).model_dump(mode="json")
        if capability_id == "select_relevant_assets":
            assert result.requirement is not None
            assert result.catalogue is not None
            return SelectRelevantAssetsInput(
                requirement=result.requirement,
                catalogue_snapshot_id=result.catalogue.snapshot_id,
                catalogue_assets=result.catalogue.asset_refs(),
                max_assets=8,
            ).model_dump(mode="json")
        if capability_id == "generate_sql_query":
            assert result.requirement is not None
            assert result.selection is not None
            return GenerateSqlQueryInput(
                requirement=result.requirement,
                selected_assets=tuple(item.asset for item in result.selection.selected),
                dialect="snowflake",
            ).model_dump(mode="json")
        if capability_id == "classify_sql":
            assert result.generated_sql is not None
            return ClassifySqlInput(sql=result.generated_sql.sql).model_dump(mode="json")
        if capability_id == "validate_query":
            assert result.generated_sql is not None
            return ValidateQueryInput(sql=result.generated_sql.sql, mode="EXPLAIN").model_dump(
                mode="json"
            )
        if capability_id == "execute_query":
            assert result.generated_sql is not None
            return ExecuteQueryInput(
                sql=result.generated_sql.sql,
                budget=Budget(max_rows=100, max_bytes=65536, max_seconds=30),
                result_mode="ROWS",
            ).model_dump(mode="json")
        return raw

    def _absorb(
        self,
        result: SliceResult,
        capability_id: str,
        output: BaseModel,
        task: MaterializedTaskModel,
    ) -> None:
        if capability_id == "discover_assets":
            dumped = DiscoverAssetsOutput.model_validate(output)
            result.catalogue = MetadataCatalog.from_assets(dumped.snapshot_id, dumped.assets)
            self._events.publish(
                result.workflow_id, "catalogue.ready", {"count": len(result.catalogue.assets)}
            )
        elif capability_id == "select_relevant_assets":
            result.selection = SelectRelevantAssetsOutput.model_validate(output)
            assert result.catalogue is not None
            for item in result.selection.selected:
                if not result.catalogue.contains(item.asset):
                    raise RuntimeError("selection is not a subset of the immutable catalogue")
        elif capability_id == "generate_sql_query":
            result.generated_sql = GenerateSqlQueryOutput.model_validate(output)
        elif capability_id == "classify_sql":
            result.classification = ClassifySqlOutput.model_validate(output)
        elif capability_id == "execute_query":
            result.execution = ExecuteQueryOutput.model_validate(output)
            result.query_tag = result.execution.query_tag
            result.provenance = self._ro.provenance(
                capability_id="execute_query",
                operation_idempotency_key=task.operation_idempotency_key,
                resolved_input_digest=task.resolved_input_digest,
            )

    async def _store_artifact(
        self, workflow_id: UUID, artifact_type: str, body: dict[str, Any], *, capability_id: str
    ) -> None:
        digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        provenance = ArtifactProvenance(
            execution_mode=ExecutionMode.MOCK,
            connector_id=None,
            connector_version=None,
            capability_id=capability_id,
            capability_version=1,
            operation_idempotency_key="0" * 64,
            resolved_input_digest=digest,
        )
        async with self._sessions() as session, session.begin():
            await ArtifactRepository(session).add(
                workflow_id=workflow_id,
                task_id=None,
                artifact_type=artifact_type,
                version=1,
                schema_version=1,
                sha256=digest,
                provenance=provenance,
                body=body,
            )

    async def _finalize_status(self, result: SliceResult) -> SliceResult:
        async with self._sessions() as session:
            workflow = await session.get(WorkflowModel, result.workflow_id)
            assert workflow is not None
            result.workflow_state = workflow.state
            result.events = tuple(
                item.event_type for item in self._events.history(result.workflow_id)
            )
        return result

    def _snapshot(self, *, pin_unknown_capability: bool) -> ContractSnapshot:
        contracts = [
            CapabilityContractRef(
                capability_id=spec.id,
                capability_contract_version=1,
                input_schema_version=1,
                output_schema_version=1,
            )
            for spec in self._capabilities.all_specs()
            if spec.id in SLICE_CAPABILITIES
        ]
        if pin_unknown_capability:
            contracts.append(
                CapabilityContractRef(
                    capability_id="missing_capability",
                    capability_contract_version=9,
                    input_schema_version=1,
                    output_schema_version=1,
                )
            )
        return ContractSnapshot(
            snapshot_id=uuid4(),
            capability_contracts=tuple(contracts),
            connector_versions={
                "snowflake_ro": self._ro.spec.version,
                "snowflake_dev": self._dev.spec.version,
            },
        )


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _persistable_health(snapshot: ConnectorHealthSnapshot) -> ConnectorHealthSnapshot:
    return snapshot.model_copy(
        update={
            "checked_at": _naive(snapshot.checked_at),
            "expires_at": _naive(snapshot.expires_at),
        }
    )


def _planning_templates(workflow_id: UUID, snapshot_id: UUID) -> tuple[TemplateSpec, ...]:
    payload = PlanPhaseInput(
        workflow_context_ref=str(workflow_id),
        phase=WorkflowState.PLANNING,
        contract_snapshot_ref=str(snapshot_id),
        capability_catalogue=(),
        constraints=PlanConstraints(max_tasks=50),
        occurrence="DESCRIPTION",
    ).model_dump(mode="json")
    return (
        TemplateSpec(
            local_id="p1",
            capability_id="plan_phase",
            capability_contract_version=1,
            connector_id=None,
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs=payload,
            timeout_seconds=120,
            max_attempts=2,
        ),
    )


def classify_sql_handler(payload: BaseModel, _context: dict[str, Any]) -> ClassifySqlOutput:
    assert isinstance(payload, ClassifySqlInput)
    return ClassifySqlOutput.model_validate(
        classify_sql_pure(payload.sql, connector_id="snowflake_ro").model_dump()
    )
