"""DE 002C offline safe-SQL slice composition."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.events import EventBus
from aide.app.parking import fail_closed_task, park_task
from aide.app.plan_validation import validate_plan
from aide.auth.grants import GrantAuthorizer, GrantForgeryError
from aide.auth.session import digest_session_token, issue_session_token
from aide.capabilities.io import (
    Budget,
    ClassifySqlInput,
    ClassifySqlOutput,
    DiscoverAssetsInput,
    DiscoverAssetsOutput,
    EmitWorkflowSummaryInput,
    EvaluateExecutionPolicyInput,
    EvaluateExecutionPolicyOutput,
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
    ValidateResultInput,
    ValidationReport,
    WorkflowSummary,
)
from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.handles import WarehouseSurface
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.registry import ConnectorRegistry
from aide.discovery.catalog import MetadataCatalog
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.enums import TargetEnv
from aide.domain.identity import canonical_json_bytes
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.sql import AssetRef, SqlClassification, SqlText
from aide.domain.states import LEGAL_TRANSITIONS, TaskState, WorkflowState
from aide.domain.tasks import TaskTemplate
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.orchestration.compatibility import evaluate_pinned_contract
from aide.orchestration.coordination import NextPhase, reduce_and_advance
from aide.orchestration.materialization import (
    TemplateSpec,
    create_phase_occurrence,
    persist_materialized_task,
)
from aide.orchestration.worker import (
    TaskClaim,
    claim_task,
    finalize_success,
    mark_dispatched,
    select_runnable_task,
)
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
    "evaluate_execution_policy",
    "execute_query",
    "validate_result",
    "emit_workflow_summary",
    "create_dataset",
}
_SQL_POLICY_CAPABILITIES = {
    "execute_query",
    "evaluate_execution_policy",
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
    generation_plan: Plan | None = None
    generated_sql: GenerateSqlQueryOutput | None = None
    classification: SqlClassification | None = None
    execution: ExecuteQueryOutput | None = None
    query_tag: str | None = None
    provenance: ArtifactProvenance | None = None
    validation: ValidationReport | None = None
    summary: WorkflowSummary | None = None
    parked: bool = False
    park_reason: str | None = None
    failed: bool = False
    fail_reason: str | None = None
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
        snowflake_ro: WarehouseSurface,
        snowflake_dev: WarehouseSurface,
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
        self.force_scope_violation = False

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
        force_scope_violation: bool = False,
        principal: PrincipalRef | None = None,
        persist_bootstrap_session: bool = True,
    ) -> SliceResult:
        self.force_scope_violation = force_scope_violation
        requested = requested_grants or frozenset({PermissionLevel.READ})
        now = datetime.now(UTC)
        actor = principal or PrincipalRef(
            principal_id=uuid4(),
            authentication_source="LOCAL_SESSION",
            roles=frozenset({Role.OPERATOR, Role.APPROVER}),
            session_id=uuid4(),
        )
        if client_supplied_effective is not None:
            raise GrantForgeryError("client supplied effective grants are not trusted")
        authorization = self._authorizer.authorize(
            actor,
            requested,
            target_environment=TargetEnv.DEV,
            decided_at=_naive(now),
        )
        if connector_unavailable:
            self._ro.force_health("UNAVAILABLE")
        snapshot = self._snapshot(pin_unknown_capability=pin_unknown_capability)
        async with self._sessions() as session, session.begin():
            if persist_bootstrap_session and principal is None:
                await SessionRepository(session).add(
                    principal=actor,
                    opaque_token_digest=digest_session_token(issue_session_token()),
                    csrf_token_digest=digest_session_token(issue_session_token()),
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
                    "principal_id": str(actor.principal_id),
                    "session_id": str(actor.session_id),
                },
            )
        workflow_id = workflow.workflow_id
        self._events.publish(
            workflow_id,
            "workflow.created",
            {"grants": sorted(item.value for item in authorization.effective)},
        )
        result = SliceResult(workflow_id=workflow_id, principal=actor, grants=authorization)
        result.requirement = self._reasoner.interpret_requirement(
            InterpretRequirementInput(text=requirement_text)
        )
        await self._store_artifact(
            workflow_id,
            "RequirementSpec",
            result.requirement.model_dump(mode="json"),
            capability_id="interpret_requirement",
        )
        planning_id = uuid4()
        await self._create_phase(
            result,
            snapshot,
            phase_run_id=planning_id,
            phase=WorkflowState.PLANNING,
            expected_generation=1,
            templates=_planning_templates(
                workflow_id,
                snapshot.snapshot_id,
                target_phase=WorkflowState.DISCOVERY,
                occurrence="ENUMERATION",
                effective_grants=authorization.effective,
            ),
            phase_exit_criteria=("planning_boundary",),
        )
        if await self._run_phase(result, phase_run_id=planning_id, snapshot=snapshot):
            return await self._finalize_status(result)
        assert result.enumeration_plan is not None
        discovery_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=discovery_id,
                phase=WorkflowState.DISCOVERY,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=validate_plan(
                    result.enumeration_plan,
                    capabilities=self._capabilities,
                    connectors=self._connectors,
                    effective_grants=result.grants.effective,
                ),
                phase_exit_criteria=result.enumeration_plan.phase_exit_criteria,
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=discovery_id, snapshot=snapshot):
            return await self._finalize_status(result)
        assert result.catalogue is not None
        sorted_assets = tuple(sorted(result.catalogue.assets, key=lambda item: item.address))
        if result.catalogue.assets != sorted_assets:
            raise RuntimeError("catalogue must be immutably sorted")
        if "asset_selection" in result.enumeration_plan.phase_exit_criteria:
            raise RuntimeError("enumeration exit criteria must be catalogue-only")
        description_plan_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=description_plan_id,
                phase=WorkflowState.PLANNING,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_planning_templates(
                    workflow_id,
                    snapshot.snapshot_id,
                    target_phase=WorkflowState.DISCOVERY,
                    occurrence="DESCRIPTION",
                    catalogue_snapshot_id=str(result.catalogue.snapshot_id),
                    catalogue_assets=result.catalogue.asset_refs(),
                    effective_grants=result.grants.effective,
                ),
                phase_exit_criteria=("planning_boundary",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=description_plan_id, snapshot=snapshot):
            return await self._finalize_status(result)
        assert result.description_plan is not None
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
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=description_id,
                phase=WorkflowState.DISCOVERY,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=validate_plan(
                    result.description_plan,
                    capabilities=self._capabilities,
                    connectors=self._connectors,
                    effective_grants=result.grants.effective,
                ),
                phase_exit_criteria=result.description_plan.phase_exit_criteria,
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=description_id, snapshot=snapshot):
            return await self._finalize_status(result)
        generation_plan_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=generation_plan_id,
                phase=WorkflowState.PLANNING,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_planning_templates(
                    workflow_id,
                    snapshot.snapshot_id,
                    target_phase=WorkflowState.GENERATION,
                    occurrence="SAFE_SQL",
                    effective_grants=result.grants.effective,
                ),
                phase_exit_criteria=("planning_boundary",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=generation_plan_id, snapshot=snapshot):
            return await self._finalize_status(result)
        assert result.generation_plan is not None
        if any(task.capability_id == "execute_query" for task in result.generation_plan.tasks):
            raise RuntimeError("execute_query must not run in GENERATION")
        generation_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=generation_id,
                phase=WorkflowState.GENERATION,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=validate_plan(
                    result.generation_plan,
                    capabilities=self._capabilities,
                    connectors=self._connectors,
                    effective_grants=result.grants.effective,
                ),
                phase_exit_criteria=result.generation_plan.phase_exit_criteria,
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=generation_id, snapshot=snapshot):
            return await self._finalize_status(result)
        policy_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=policy_id,
                phase=WorkflowState.POLICY_CHECK,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_policy_templates(),
                phase_exit_criteria=("policy_allow_execute",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=policy_id, snapshot=snapshot):
            return await self._finalize_status(result)
        execution_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=execution_id,
                phase=WorkflowState.EXECUTION,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_execution_templates(),
                phase_exit_criteria=("execution_result",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=execution_id, snapshot=snapshot):
            return await self._finalize_status(result)
        if result.execution is None or result.generated_sql is None:
            raise RuntimeError("execution produced no validated output")
        validation_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=validation_id,
                phase=WorkflowState.VALIDATION,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_validation_templates(),
                phase_exit_criteria=("validation_report",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=validation_id, snapshot=snapshot):
            return await self._finalize_status(result)
        if result.validation is None or not result.validation.passed:
            raise RuntimeError("deterministic validation failed")
        delivery_plan_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=delivery_plan_id,
                phase=WorkflowState.PLANNING,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_planning_templates(
                    workflow_id,
                    snapshot.snapshot_id,
                    target_phase=WorkflowState.DELIVERY,
                    occurrence="DELIVERY",
                    effective_grants=result.grants.effective,
                ),
                phase_exit_criteria=("planning_boundary",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=delivery_plan_id, snapshot=snapshot):
            return await self._finalize_status(result)
        delivery_id = uuid4()
        delivery_plan = result.extra.get("delivery_plan")
        delivery_templates = (
            validate_plan(
                delivery_plan,
                capabilities=self._capabilities,
                connectors=self._connectors,
                effective_grants=result.grants.effective,
            )
            if isinstance(delivery_plan, Plan)
            else _delivery_templates()
        )
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=delivery_id,
                phase=WorkflowState.DELIVERY,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=delivery_templates,
                phase_exit_criteria=("workflow_summary",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=delivery_id, snapshot=snapshot):
            return await self._finalize_status(result)
        await self._reduce_current(result)
        await self._complete_from_delivery(result)
        return await self._finalize_status(result)

    async def _create_phase(
        self,
        result: SliceResult,
        snapshot: ContractSnapshot,
        *,
        phase_run_id: UUID,
        phase: WorkflowState,
        expected_generation: int,
        templates: tuple[TemplateSpec, ...],
        phase_exit_criteria: tuple[str, ...],
    ) -> None:
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, result.workflow_id)
            assert workflow_row is not None
            _ensure_legal(workflow_row.state, phase)
            await create_phase_occurrence(
                session,
                workflow_id=result.workflow_id,
                phase_run_id=phase_run_id,
                phase=phase,
                expected_workflow_version=workflow_row.version,
                expected_generation=expected_generation,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=templates,
                phase_exit_criteria=phase_exit_criteria,
            )
        self._events.publish(
            result.workflow_id,
            "phase.created",
            {"phase": phase.value, "generation": expected_generation},
        )

    async def _advance(
        self,
        result: SliceResult,
        snapshot: ContractSnapshot,
        target: NextPhase,
    ) -> bool:
        del snapshot
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, result.workflow_id)
            assert workflow_row is not None
            phase_run = await session.get(PhaseRunModel, workflow_row.active_phase_run_id)
            assert phase_run is not None
            _ensure_legal(workflow_row.state, target.phase)
            advanced = await reduce_and_advance(
                session,
                workflow_id=result.workflow_id,
                expected_workflow_version=workflow_row.version,
                expected_generation=phase_run.generation,
                next_phase=target,
            )
        if advanced is None:
            return result.parked or result.failed
        self._events.publish(result.workflow_id, "phase.created", {"phase": target.phase.value})
        return False

    async def _reduce_current(self, result: SliceResult) -> None:
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, result.workflow_id)
            assert workflow_row is not None
            phase_run = await session.get(PhaseRunModel, workflow_row.active_phase_run_id)
            assert phase_run is not None
            await reduce_and_advance(
                session,
                workflow_id=result.workflow_id,
                expected_workflow_version=workflow_row.version,
                expected_generation=phase_run.generation,
                next_phase=None,
            )

    async def _complete_from_delivery(self, result: SliceResult) -> None:
        async with self._sessions() as session, session.begin():
            workflow_row = await session.get(WorkflowModel, result.workflow_id)
            assert workflow_row is not None
            _ensure_legal(workflow_row.state, WorkflowState.COMPLETED)
            workflow_row.state = WorkflowState.COMPLETED.value
            workflow_row.finished_at = _naive(datetime.now(UTC))
            workflow_row.version += 1
            await append_audit_event(
                session,
                workflow_id=result.workflow_id,
                event_type="WORKFLOW_COMPLETED",
                payload={"outcome": result.summary.outcome if result.summary else "NO_DELIVERY"},
            )

    async def _run_phase(
        self, result: SliceResult, *, phase_run_id: UUID, snapshot: ContractSnapshot
    ) -> bool:
        while True:
            await self._materialize_ready(result, phase_run_id=phase_run_id, snapshot=snapshot)
            parked_by_contract = False
            async with self._sessions() as session, session.begin():
                now = _naive(datetime.now(UTC))
                candidate = await select_runnable_task(
                    session,
                    now=now,
                    workflow_id=result.workflow_id,
                    phase_run_id=phase_run_id,
                )
                if candidate is None:
                    claim = None
                else:
                    compatible = await evaluate_pinned_contract(
                        session,
                        task_id=candidate.task_id,
                        capabilities=self._capabilities,
                        connectors=self._connectors,
                    )
                    if not compatible:
                        parked_by_contract = True
                        claim = None
                    else:
                        claim = await claim_task(
                            session,
                            owner=OWNER,
                            now=now,
                            lease_duration=timedelta(seconds=30),
                            workflow_id=result.workflow_id,
                            phase_run_id=phase_run_id,
                            task_id=candidate.task_id,
                        )
            if parked_by_contract:
                result.parked = True
                result.park_reason = "CONTRACT_VERSION_UNAVAILABLE"
                return True
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
                    failed_rows = (
                        await session.scalars(
                            select(MaterializedTaskModel).where(
                                MaterializedTaskModel.phase_run_id == phase_run_id,
                                MaterializedTaskModel.status == TaskState.FAILED.value,
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
                if failed_rows:
                    result.failed = True
                    result.fail_reason = failed_rows[0].disposition_reason
                    return True
                if remaining:
                    continue
                return False
            if await self._execute_claim(result, claim, snapshot, phase_run_id):
                return True

    async def _execute_claim(
        self,
        result: SliceResult,
        claim: TaskClaim,
        snapshot: ContractSnapshot,
        phase_run_id: UUID,
    ) -> bool:
        async with self._sessions() as session, session.begin():
            task = await session.get(MaterializedTaskModel, claim.task_id)
            assert task is not None
            if task.workflow_id != result.workflow_id or task.phase_run_id != phase_run_id:
                raise RuntimeError("claim escaped the current workflow or phase")
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
            sql_classification = (
                result.classification if task.capability_id in _SQL_POLICY_CAPABILITIES else None
            )

            async def _dispatch() -> None:
                dispatched = await mark_dispatched(session, claim)
                if not dispatched:
                    raise RuntimeError("lost claim before policy-allowed dispatch")

            try:
                output, decision = await self._tools.invoke(
                    session,
                    capability_id=task.capability_id,
                    payload=task.resolved_inputs,
                    context=context,
                    principal=result.principal,
                    authorization=result.grants,
                    connector_id=task.connector_id,
                    connector_health=health,
                    sql_classification=sql_classification,
                    on_policy_allow=_dispatch,
                )
            except PolicyParked as exc:
                reason = exc.decision.reasons[0].value if exc.decision.reasons else "PARKED"
                await park_task(
                    session,
                    task_id=task.task_id,
                    reason=reason,
                    now=_naive(datetime.now(UTC)),
                    routing=exc.decision.routing,
                    reasons=tuple(item.value for item in exc.decision.reasons),
                )
                result.parked = True
                result.park_reason = reason
                return True
            except PolicyDenied as exc:
                reason = exc.decision.reasons[0].value if exc.decision.reasons else "DENIED"
                await fail_closed_task(
                    session,
                    task_id=task.task_id,
                    reason=reason,
                    now=_naive(datetime.now(UTC)),
                    routing=exc.decision.routing,
                    reasons=tuple(item.value for item in exc.decision.reasons),
                )
                result.failed = True
                result.fail_reason = reason
                return True
            dumped = output.model_dump(mode="json")
            ok = await finalize_success(
                session, claim=claim, output=dumped, now=_naive(datetime.now(UTC))
            )
            if not ok:
                raise RuntimeError("ambiguous success cannot pass without validated output")
            self._absorb(result, task.capability_id, output, task)
            artifact_type = {
                "plan_phase": "Plan",
                "validate_result": "ValidationReport",
                "emit_workflow_summary": "WorkflowSummary",
            }.get(task.capability_id)
            if artifact_type is not None:
                await ArtifactRepository(session).add(
                    workflow_id=result.workflow_id,
                    task_id=task.task_id,
                    artifact_type=artifact_type,
                    version=1,
                    schema_version=1,
                    sha256=hashlib.sha256(canonical_json_bytes(dumped)).hexdigest(),
                    provenance=ArtifactProvenance(
                        execution_mode=ExecutionMode.MOCK,
                        connector_id=None,
                        connector_version=None,
                        capability_id=task.capability_id,
                        capability_version=1,
                        operation_idempotency_key=task.operation_idempotency_key,
                        resolved_input_digest=task.resolved_input_digest,
                    ),
                    body=dumped,
                )
            del decision
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
        if capability_id == "plan_phase":
            payload = dict(raw)
            if result.catalogue is not None and payload.get("occurrence") == "DESCRIPTION":
                payload["catalogue_snapshot_id"] = str(result.catalogue.snapshot_id)
                payload["catalogue_assets"] = [
                    item.model_dump(mode="json") for item in result.catalogue.asset_refs()
                ]
            return payload
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
        if capability_id == "evaluate_execution_policy":
            assert result.generated_sql is not None
            return EvaluateExecutionPolicyInput(
                target_capability_id="execute_query",
                connector_id="snowflake_ro",
                sql=result.generated_sql.sql,
            ).model_dump(mode="json")
        if capability_id == "execute_query":
            assert result.generated_sql is not None
            return ExecuteQueryInput(
                sql=result.generated_sql.sql,
                budget=Budget(max_rows=100, max_bytes=65536, max_seconds=30),
                result_mode="ROWS",
            ).model_dump(mode="json")
        if capability_id == "validate_result":
            assert result.execution is not None
            assert result.generated_sql is not None
            return ValidateResultInput(
                row_count=result.execution.row_count,
                rows=result.execution.rows,
                expected_columns=result.generated_sql.expected_columns,
            ).model_dump(mode="json")
        if capability_id == "emit_workflow_summary":
            return EmitWorkflowSummaryInput(
                outcome="NO_DELIVERY",
                validation_passed=bool(result.validation and result.validation.passed),
                row_count=result.execution.row_count if result.execution else 0,
                sql_dialect=result.generated_sql.sql.dialect if result.generated_sql else None,
            ).model_dump(mode="json")
        return raw

    def _absorb(
        self,
        result: SliceResult,
        capability_id: str,
        output: BaseModel,
        task: MaterializedTaskModel,
    ) -> None:
        if capability_id == "plan_phase":
            plan = Plan.model_validate(output)
            if plan.phase == WorkflowState.DISCOVERY:
                if "asset_selection" in plan.phase_exit_criteria:
                    result.description_plan = plan
                else:
                    result.enumeration_plan = plan
            elif plan.phase == WorkflowState.GENERATION:
                result.generation_plan = plan
            elif plan.phase == WorkflowState.DELIVERY:
                result.extra["delivery_plan"] = plan
        elif capability_id == "discover_assets":
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
            generated = GenerateSqlQueryOutput.model_validate(output)
            if self.force_scope_violation:
                generated = generated.model_copy(
                    update={
                        "sql": SqlText(
                            dialect="snowflake",
                            text="SELECT 1 FROM OTHER.SECRET.TABLE",
                        )
                    }
                )
            result.generated_sql = generated
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
        elif capability_id == "validate_result":
            result.validation = ValidationReport.model_validate(output)
        elif capability_id == "emit_workflow_summary":
            result.summary = WorkflowSummary.model_validate(output)

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


def _ensure_legal(current: WorkflowState | str, target: WorkflowState) -> None:
    source = current if isinstance(current, WorkflowState) else WorkflowState(current)
    if (source, target) not in LEGAL_TRANSITIONS:
        raise RuntimeError(f"illegal transition {source.value} -> {target.value}")


def _planning_templates(
    workflow_id: UUID,
    snapshot_id: UUID,
    *,
    target_phase: WorkflowState,
    occurrence: Literal["ENUMERATION", "DESCRIPTION", "SAFE_SQL", "DELIVERY"],
    effective_grants: frozenset[PermissionLevel],
    catalogue_snapshot_id: str | None = None,
    catalogue_assets: tuple[AssetRef, ...] = (),
) -> tuple[TemplateSpec, ...]:
    payload = PlanPhaseInput(
        workflow_context_ref=str(workflow_id),
        phase=target_phase,
        contract_snapshot_ref=str(snapshot_id),
        capability_catalogue=(),
        constraints=PlanConstraints(
            max_tasks=50,
            effective_grants=tuple(sorted(item.value for item in effective_grants)),
        ),
        occurrence=occurrence,
        catalogue_snapshot_id=catalogue_snapshot_id,
        catalogue_assets=catalogue_assets,
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


def _policy_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="pc.01",
            capability_id="evaluate_execution_policy",
            capability_contract_version=1,
            connector_id="snowflake_ro",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=30,
            max_attempts=2,
        ),
    )


def _execution_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="e1",
            capability_id="execute_query",
            capability_contract_version=1,
            connector_id="snowflake_ro",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=30,
            max_attempts=2,
        ),
    )


def _validation_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="val.01",
            capability_id="validate_result",
            capability_contract_version=1,
            connector_id=None,
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=30,
            max_attempts=1,
        ),
    )


def _delivery_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="del.01",
            capability_id="emit_workflow_summary",
            capability_contract_version=1,
            connector_id=None,
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={"outcome": "NO_DELIVERY"},
            timeout_seconds=30,
            max_attempts=1,
        ),
    )


def classify_sql_handler(payload: BaseModel, _context: dict[str, Any]) -> ClassifySqlOutput:
    assert isinstance(payload, ClassifySqlInput)
    return ClassifySqlOutput.model_validate(
        classify_sql_pure(payload.sql, connector_id="snowflake_ro").model_dump()
    )


def evaluate_execution_policy_handler(
    payload: BaseModel, _context: dict[str, Any]
) -> EvaluateExecutionPolicyOutput:
    assert isinstance(payload, EvaluateExecutionPolicyInput)
    return EvaluateExecutionPolicyOutput(decision="ALLOW", routing="EXECUTE", reasons=())


def validate_result_handler(payload: BaseModel, _context: dict[str, Any]) -> ValidationReport:
    assert isinstance(payload, ValidateResultInput)
    return validate_query_result(
        ExecuteQueryOutput(
            rows=payload.rows,
            row_count=payload.row_count,
            duration_ms=1,
        ),
        expected_columns=payload.expected_columns,
    )


def emit_workflow_summary_handler(payload: BaseModel, context: dict[str, Any]) -> WorkflowSummary:
    assert isinstance(payload, EmitWorkflowSummaryInput)
    return WorkflowSummary(
        outcome=payload.outcome,
        workflow_id=_as_uuid(context["workflow_id"]),
        validation_passed=payload.validation_passed,
        row_count=payload.row_count,
        sql_dialect=payload.sql_dialect,
    )


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
