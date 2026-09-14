"""Deterministic Interview MVP Supervisor.

Supervisor is an application service over the accepted orchestrator. It authenticates,
pins contracts and the Twin snapshot, materializes the fixed customer-revenue workflow,
dispatches every connector action through the Governed Tool Gateway, and advances
state only from persisted typed outcomes. It is not an autonomous tool loop.
"""

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
from aide.app.gateway import GatewayOutcome, GovernedToolGateway
from aide.app.groups import (
    interpret_customer_revenue_request,
    plan_interview_phase,
    propose_relevant_assets,
)
from aide.auth.grants import GrantAuthorizer, GrantForgeryError
from aide.auth.session import digest_session_token, issue_session_token
from aide.capabilities.io import (
    CompileTransformationInput,
    CompileTransformationOutput,
    CreateTransformationInput,
    CreateTransformationOutput,
    DescribeAssetInput,
    DescribeAssetOutput,
    DiscoverAssetsInput,
    DiscoverAssetsOutput,
    DiscoveryScope,
    EvaluateExecutionPolicyInput,
    ExecuteTransformationInput,
    ExecuteTransformationOutput,
    GenerateTransformationInput,
    GenerateTransformationOutput,
    LoadManifestSourcesInput,
    LoadManifestSourcesOutput,
    ModelDesign,
    ParseTransformationInput,
    ParseTransformationOutput,
    Plan,
    PlanConstraints,
    PlanPhaseInput,
    ProfileEstateInput,
    ProfileEstateOutput,
    RequirementSpec,
    RunTestsInput,
    RunTestsOutput,
    SelectRelevantAssetsOutput,
    TransformationProjectRef,
    ValidateInterviewQualityInput,
    ValidationReport,
)
from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.snowflake.manifest import tiny_manifest_digest
from aide.discovery.catalog import MetadataCatalog
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.enums import TargetEnv
from aide.domain.identity import canonical_json_bytes
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.sql import AssetRef, SqlText
from aide.domain.states import LEGAL_TRANSITIONS, TaskState, WorkflowState
from aide.domain.tasks import TaskTemplate
from aide.domain.twin import EvidenceReference, SourceAuthorityRef, TwinAssetKind, TwinSnapshot
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.generation.vantara import generate_vantara_transformation
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.modelling.engine import decide_architecture
from aide.modelling.service import build_propose_input
from aide.modelling.validators import validate_model_design
from aide.modelling.vantara import vantara_modelling_context, vantara_selected_addresses
from aide.orchestration.compatibility import evaluate_pinned_contract
from aide.orchestration.coordination import NextPhase, reduce_and_advance
from aide.orchestration.materialization import (
    TemplateSpec,
    create_phase_occurrence,
    persist_materialized_task,
)
from aide.orchestration.worker import TaskClaim, claim_task, select_runnable_task
from aide.persistence.audit import append_audit_event
from aide.persistence.models import (
    MaterializedTaskModel,
    PhaseRunModel,
    TaskTemplateModel,
    WorkflowModel,
)
from aide.persistence.repositories import (
    ArtifactRepository,
    ContractSnapshotRepository,
    GrantRepository,
    SessionRepository,
    WorkflowRepository,
)
from aide.persistence.twin import TwinRepository
from aide.profiling.artifacts import ProfilingRunResult
from aide.profiling.fixtures import asset_slug, demo_selected_assets
from aide.reasoning.propose_model_design import propose_model_design
from aide.twin.capture import capture_snowflake_metadata
from aide.twin.context import (
    EstateAccessPolicy,
    EstateContextLimits,
    EstateContextRequest,
    assemble_estate_context,
)
from aide.twin.snapshot import build_twin_snapshot

OWNER = "mvp002-supervisor"
INTERVIEW_CAPABILITIES = frozenset(
    {
        "plan_phase",
        "discover_assets",
        "describe_asset",
        "profile_estate",
        "propose_model_design",
        "generate_transformation",
        "create_transformation",
        "parse_transformation",
        "compile_transformation",
        "evaluate_execution_policy",
        "load_manifest_sources",
        "execute_transformation",
        "run_tests",
        "validate_interview_quality",
    }
)
LEGAL_INTERVIEW_PHASES = (
    WorkflowState.RECEIVED,
    WorkflowState.PLANNING,
    WorkflowState.DISCOVERY,
    WorkflowState.PLANNING,
    WorkflowState.PROFILING,
    WorkflowState.PLANNING,
    WorkflowState.DESIGN,
    WorkflowState.PLANNING,
    WorkflowState.GENERATION,
    WorkflowState.POLICY_CHECK,
    WorkflowState.EXECUTION,
    WorkflowState.VALIDATION,
)
OPERATOR_REQUESTED = frozenset(
    {
        PermissionLevel.READ,
        PermissionLevel.DEVELOPMENT_EXECUTE,
        PermissionLevel.DEVELOPMENT_WRITE,
    }
)


@dataclass
class InterviewResult:
    workflow_id: UUID
    principal: PrincipalRef
    grants: GrantAuthorization
    requirement: RequirementSpec | None = None
    catalogue: MetadataCatalog | None = None
    selection: SelectRelevantAssetsOutput | None = None
    descriptions: list[DescribeAssetOutput] = field(default_factory=list)
    twin_snapshot: TwinSnapshot | None = None
    estate_context_sha256: str | None = None
    profiling: ProfileEstateOutput | None = None
    profiling_run: ProfilingRunResult | None = None
    model_design: ModelDesign | None = None
    generated: GenerateTransformationOutput | None = None
    project_state_id: UUID | None = None
    parse_ok: bool = False
    compile_ok: bool = False
    load_ok: bool = False
    execute_ok: bool = False
    tests_ok: bool = False
    quality: ValidationReport | None = None
    fixture_version: Literal["v1", "v2"] = "v1"
    parked: bool = False
    park_reason: str | None = None
    failed: bool = False
    fail_reason: str | None = None
    workflow_states: list[str] = field(default_factory=list)
    events: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


class InterviewSupervisor:
    """Fixed Interview MVP workflow. Capability groups never receive this object."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        capabilities: CapabilityRegistry,
        connectors: ConnectorRegistry,
        gateway: GovernedToolGateway,
        events: EventBus,
        execution_mode: ExecutionMode = ExecutionMode.MOCK,
    ) -> None:
        self._sessions = session_factory
        self._capabilities = capabilities
        self._connectors = connectors
        self._gateway = gateway
        self._events = events
        self._authorizer = GrantAuthorizer()
        self._execution_mode = execution_mode

    async def run_customer_revenue(
        self,
        requirement_text: str,
        *,
        requested_grants: frozenset[PermissionLevel] | None = None,
        client_supplied_effective: frozenset[PermissionLevel] | None = None,
        principal: PrincipalRef | None = None,
        persist_bootstrap_session: bool = True,
        fixture_version: Literal["v1", "v2"] = "v1",
    ) -> InterviewResult:
        if client_supplied_effective is not None:
            raise GrantForgeryError("client supplied effective grants are not trusted")
        now = datetime.now(UTC)
        actor = principal or PrincipalRef(
            principal_id=uuid4(),
            authentication_source="LOCAL_SESSION",
            roles=frozenset({Role.OPERATOR, Role.APPROVER}),
            session_id=uuid4(),
        )
        authorization = self._authorizer.authorize(
            actor,
            requested_grants or OPERATOR_REQUESTED,
            target_environment=TargetEnv.DEV,
            decided_at=_naive(now),
        )
        snapshot = self._snapshot()
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
            await append_audit_event(
                session,
                workflow_id=workflow.workflow_id,
                event_type="WORKFLOW_CREATED",
                payload={
                    "effective_grants": sorted(item.value for item in authorization.effective),
                    "supervisor": OWNER,
                },
                actor={
                    "kind": "PRINCIPAL",
                    "principal_id": str(actor.principal_id),
                    "session_id": str(actor.session_id),
                },
            )
        result = InterviewResult(
            workflow_id=workflow.workflow_id,
            principal=actor,
            grants=authorization,
            workflow_states=[WorkflowState.RECEIVED.value],
            fixture_version=fixture_version,
        )
        result.requirement = interpret_customer_revenue_request(requirement_text)
        await self._store_artifact(
            result.workflow_id,
            "RequirementSpec",
            result.requirement.model_dump(mode="json"),
            capability_id="interpret_requirement",
        )
        selected = demo_selected_assets()
        planning_id = uuid4()
        await self._create_phase(
            result,
            snapshot,
            phase_run_id=planning_id,
            phase=WorkflowState.PLANNING,
            expected_generation=1,
            templates=_planning_templates(
                result.workflow_id, snapshot.snapshot_id, WorkflowState.DISCOVERY, authorization
            ),
            phase_exit_criteria=("planning_boundary",),
        )
        if await self._run_phase(result, phase_run_id=planning_id, snapshot=snapshot):
            return await self._finalize_status(result)
        discovery_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=discovery_id,
                phase=WorkflowState.DISCOVERY,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_discovery_templates(selected),
                phase_exit_criteria=("catalogue", "descriptions"),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=discovery_id, snapshot=snapshot):
            return await self._finalize_status(result)
        assert result.catalogue is not None
        result.selection = propose_relevant_assets(
            DiscoverAssetsOutput(
                assets=result.catalogue.assets,
                snapshot_id=result.catalogue.snapshot_id,
            )
        )
        if not await self._pin_twin(result, snapshot):
            return await self._finalize_status(result)
        if await self._plan_and_run(
            result,
            snapshot,
            target=WorkflowState.PROFILING,
            templates=_profiling_templates(selected, fixture_version),
            exit_criteria=("estate_profiles",),
        ):
            return await self._finalize_status(result)
        if await self._plan_and_run(
            result,
            snapshot,
            target=WorkflowState.DESIGN,
            templates=_design_templates(),
            exit_criteria=("architecture_decision", "model_design"),
        ):
            return await self._finalize_status(result)
        if not self._accept_design(result):
            return await self._finalize_status(result)
        if await self._plan_and_run(
            result,
            snapshot,
            target=WorkflowState.GENERATION,
            templates=_generation_templates(),
            exit_criteria=("generated_artifacts", "parsed", "compiled"),
        ):
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
                phase_exit_criteria=("dev_sources", "transformation_result"),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=execution_id, snapshot=snapshot):
            return await self._finalize_status(result)
        validation_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=validation_id,
                phase=WorkflowState.VALIDATION,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_validation_templates(),
                phase_exit_criteria=("dbt_tests", "quality_assertions"),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=validation_id, snapshot=snapshot):
            return await self._finalize_status(result)
        await self._reduce_current(result)
        return await self._finalize_status(result)

    async def _plan_and_run(
        self,
        result: InterviewResult,
        snapshot: ContractSnapshot,
        *,
        target: WorkflowState,
        templates: tuple[TemplateSpec, ...],
        exit_criteria: tuple[str, ...],
    ) -> bool:
        planning_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=planning_id,
                phase=WorkflowState.PLANNING,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_planning_templates(
                    result.workflow_id, snapshot.snapshot_id, target, result.grants
                ),
                phase_exit_criteria=("planning_boundary",),
            ),
        ):
            return True
        if await self._run_phase(result, phase_run_id=planning_id, snapshot=snapshot):
            return True
        target_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=target_id,
                phase=target,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=templates,
                phase_exit_criteria=exit_criteria,
            ),
        ):
            return True
        return await self._run_phase(result, phase_run_id=target_id, snapshot=snapshot)

    async def _pin_twin(self, result: InterviewResult, snapshot: ContractSnapshot) -> bool:
        del snapshot
        assert result.catalogue is not None
        wanted = set(vantara_selected_addresses())
        filtered_assets = tuple(item for item in result.catalogue.assets if item.address in wanted)
        if len(filtered_assets) != len(wanted):
            result.failed = True
            result.fail_reason = "LOCKED_ASSETS_MISSING"
            return False
        descriptions = tuple(sorted(result.descriptions, key=lambda item: item.asset.address))
        if {item.asset.address for item in descriptions} != wanted:
            result.failed = True
            result.fail_reason = "DESCRIPTIONS_INCOMPLETE"
            return False
        now = _naive(datetime.now(UTC))
        authority = SourceAuthorityRef(
            authority_id="snowflake_ro",
            contract_version=self._connectors.get("snowflake_ro").version,
            scope=("VANTARA_RAW",),
        )
        body = {
            "assets": [item.model_dump(mode="json") for item in filtered_assets],
            "descriptions": [item.model_dump(mode="json") for item in descriptions],
        }
        digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        evidence = EvidenceReference(
            evidence_ref_id=uuid4(),
            evidence_type="snowflake.metadata",
            media_type="application/json",
            sha256=digest,
            size_bytes=len(canonical_json_bytes(body)),
            execution_mode=self._execution_mode,
            source_authority=authority,
            producer_operation_key=digest,
            created_at=now,
        )
        discovered = DiscoverAssetsOutput(
            assets=filtered_assets,
            snapshot_id=result.catalogue.snapshot_id,
        )
        batch = capture_snowflake_metadata(
            discovered=discovered,
            descriptions=descriptions,
            source_authority=authority,
            evidence_ref_id=evidence.evidence_ref_id,
            observed_at=now,
            fresh_until=now + timedelta(hours=24),
        )
        async with self._sessions() as session, session.begin():
            twins = TwinRepository(session)
            await twins.add_evidence_reference(evidence)
            persisted = await twins.persist_capture_batch(batch)
            snap = build_twin_snapshot(
                assets=persisted.assets,
                relationships=persisted.relationships,
                observations=persisted.observations,
                evidence_references=(evidence,),
                captured_at=now,
                capture_cutoff=now,
            )
            await twins.add_snapshot(snap)
            pinned = await twins.pin_snapshot(
                workflow_id=result.workflow_id, twin_snapshot_id=snap.twin_snapshot_id
            )
            records = await twins.load_snapshot(pinned.twin_snapshot_id)
            dataset_ids = frozenset(
                item.asset_id for item in records.assets if item.kind is TwinAssetKind.DATASET
            )
            assembled = assemble_estate_context(
                snapshot=records.snapshot,
                assets=records.assets,
                relationships=records.relationships,
                observations=records.observations,
                evidence_references=records.evidence_references,
                access=EstateAccessPolicy(
                    effective_grants=result.grants.effective,
                    allowed_asset_ids=dataset_ids,
                    allowed_authority_ids=frozenset({"snowflake_ro"}),
                ),
                request=EstateContextRequest(
                    request_terms=("customer", "revenue", "invoice", "payment"),
                    mandatory_asset_ids=dataset_ids,
                ),
                limits=EstateContextLimits(),
            )
        result.twin_snapshot = pinned
        result.estate_context_sha256 = assembled.context.estate_context_sha256
        await append_audit_outside(
            self._sessions,
            workflow_id=result.workflow_id,
            event_type="TWIN_SNAPSHOT_PINNED",
            payload={
                "twin_snapshot_id": str(pinned.twin_snapshot_id),
                "manifest_sha256": pinned.manifest_sha256,
                "estate_context_sha256": assembled.context.estate_context_sha256,
            },
        )
        return True

    def _accept_design(self, result: InterviewResult) -> bool:
        incomplete = (
            result.model_design is None
            or result.profiling_run is None
            or result.requirement is None
        )
        if incomplete:
            result.failed = True
            result.fail_reason = "DESIGN_INCOMPLETE"
            return False
        design = result.model_design
        run = result.profiling_run
        requirement = result.requirement
        assert design is not None
        assert run is not None
        assert requirement is not None
        selected = demo_selected_assets()
        decision = decide_architecture(
            requirement,
            selected=selected,
            run=run,
            context=vantara_modelling_context(),
        )
        profiles, _relationships, duplicates, _summary = _evidence(run)
        validation = validate_model_design(
            design,
            decision,
            selected=selected,
            profiles=profiles,
            duplicates=duplicates,
            context=vantara_modelling_context(),
        )
        result.extra["architecture_decision"] = decision
        result.extra["design_validation"] = validation
        if not validation.passed:
            result.failed = True
            result.fail_reason = "DESIGN_INVALID"
            return False
        return True

    async def _create_phase(
        self,
        result: InterviewResult,
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
        result.workflow_states.append(phase.value)
        self._events.publish(
            result.workflow_id,
            "phase.created",
            {"phase": phase.value, "generation": expected_generation},
        )

    async def _advance(
        self, result: InterviewResult, snapshot: ContractSnapshot, target: NextPhase
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
        result.workflow_states.append(target.phase.value)
        self._events.publish(result.workflow_id, "phase.created", {"phase": target.phase.value})
        return False

    async def _reduce_current(self, result: InterviewResult) -> None:
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

    async def _run_phase(
        self, result: InterviewResult, *, phase_run_id: UUID, snapshot: ContractSnapshot
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
                    timeout_seconds = 30
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
                        timeout_seconds = 30
                    else:
                        timeout_seconds = max(candidate.timeout_seconds, 30)
                        claim = await claim_task(
                            session,
                            owner=OWNER,
                            now=now,
                            lease_duration=timedelta(seconds=timeout_seconds),
                            workflow_id=result.workflow_id,
                            phase_run_id=phase_run_id,
                            task_id=candidate.task_id,
                        )
            if parked_by_contract:
                result.parked = True
                result.park_reason = "CONTRACT_VERSION_UNAVAILABLE"
                return True
            if claim is None:
                if await self._phase_blocked(result, phase_run_id):
                    return True
                async with self._sessions() as session:
                    remaining = (
                        await session.scalars(
                            select(MaterializedTaskModel).where(
                                MaterializedTaskModel.phase_run_id == phase_run_id,
                                MaterializedTaskModel.status.in_(
                                    [
                                        TaskState.READY.value,
                                        TaskState.CLAIMED.value,
                                        TaskState.RUNNING.value,
                                        TaskState.RETRY_WAIT.value,
                                    ]
                                ),
                            )
                        )
                    ).all()
                if remaining:
                    continue
                return False
            if await self._execute_claim(result, claim, phase_run_id):
                return True

    async def _phase_blocked(self, result: InterviewResult, phase_run_id: UUID) -> bool:
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
        if parked_rows:
            result.parked = True
            result.park_reason = parked_rows[0].disposition_reason
            return True
        if failed_rows:
            result.failed = True
            result.fail_reason = failed_rows[0].disposition_reason
            return True
        return False

    async def _execute_claim(
        self, result: InterviewResult, claim: TaskClaim, phase_run_id: UUID
    ) -> bool:
        async with self._sessions() as session:
            task = await session.get(MaterializedTaskModel, claim.task_id)
            assert task is not None
            if task.workflow_id != result.workflow_id or task.phase_run_id != phase_run_id:
                raise RuntimeError("claim escaped the current workflow or phase")
            capability_id = task.capability_id
        outcome = await self._gateway.execute(
            claim, principal=result.principal, authorization=result.grants
        )
        return self._absorb_outcome(result, capability_id, outcome)

    def _absorb_outcome(
        self, result: InterviewResult, capability_id: str, outcome: GatewayOutcome
    ) -> bool:
        if outcome.status in {"PARKED", "AWAITING_APPROVAL"}:
            result.parked = True
            result.park_reason = outcome.failure_classification
            return True
        if outcome.status in {"FAILED", "STALE"}:
            result.failed = True
            result.fail_reason = outcome.failure_classification or outcome.status
            return True
        if outcome.status == "RETRY_WAIT":
            return False
        if outcome.status != "SUCCEEDED" or outcome.output is None:
            result.failed = True
            result.fail_reason = outcome.failure_classification or outcome.status
            return True
        self._absorb(result, capability_id, outcome.output)
        intents = result.extra.setdefault("intent_ids", [])
        if outcome.intent_id is not None:
            intents.append(str(outcome.intent_id))
        evidence = result.extra.setdefault("evidence_ref_ids", [])
        if outcome.evidence_ref_id is not None:
            evidence.append(str(outcome.evidence_ref_id))
        return result.failed or result.parked

    async def _materialize_ready(
        self, result: InterviewResult, *, phase_run_id: UUID, snapshot: ContractSnapshot
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
        self, result: InterviewResult, capability_id: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        if capability_id == "plan_phase":
            return raw
        if capability_id == "discover_assets":
            return DiscoverAssetsInput(
                scope=DiscoveryScope(databases=("VANTARA_RAW",), include_views=False)
            ).model_dump(mode="json")
        if capability_id == "propose_model_design":
            assert result.requirement is not None
            assert result.profiling_run is not None
            selected = demo_selected_assets()
            decision = decide_architecture(
                result.requirement,
                selected=selected,
                run=result.profiling_run,
                context=vantara_modelling_context(),
            )
            return build_propose_input(
                result.requirement, decision, result.profiling_run, selected
            ).model_dump(mode="json")
        if capability_id == "generate_transformation":
            assert result.model_design is not None
            return GenerateTransformationInput(
                workflow_id=result.workflow_id, model_design=result.model_design
            ).model_dump(mode="json")
        if capability_id == "create_transformation":
            assert result.generated is not None
            return CreateTransformationInput(
                files=result.generated.files,
                project_ref=TransformationProjectRef(project_id="vantara_project"),
                mode="REPLACE",
            ).model_dump(mode="json")
        if capability_id == "parse_transformation":
            assert result.project_state_id is not None
            return ParseTransformationInput(project_state_id=result.project_state_id).model_dump(
                mode="json"
            )
        if capability_id == "compile_transformation":
            assert result.project_state_id is not None
            return CompileTransformationInput(project_state_id=result.project_state_id).model_dump(
                mode="json"
            )
        if capability_id == "evaluate_execution_policy":
            return EvaluateExecutionPolicyInput(
                target_capability_id="execute_transformation",
                connector_id="dbt_dev",
                sql=SqlText(dialect="snowflake", text="SELECT 1"),
            ).model_dump(mode="json")
        if capability_id == "load_manifest_sources":
            return LoadManifestSourcesInput(
                fixture_version="v1",
                manifest_sha256=tiny_manifest_digest(),
                selected_addresses=vantara_selected_addresses(),
            ).model_dump(mode="json")
        if capability_id == "execute_transformation":
            assert result.project_state_id is not None
            return ExecuteTransformationInput(project_state_id=result.project_state_id).model_dump(
                mode="json"
            )
        if capability_id == "run_tests":
            assert result.project_state_id is not None
            return RunTestsInput(project_state_id=result.project_state_id).model_dump(mode="json")
        if capability_id == "validate_interview_quality":
            assert result.project_state_id is not None
            return ValidateInterviewQualityInput(
                project_state_id=result.project_state_id,
                required_models=REQUIRED_DEMO_MODELS,
            ).model_dump(mode="json")
        return raw

    def _absorb(self, result: InterviewResult, capability_id: str, output: BaseModel) -> None:
        if capability_id == "plan_phase":
            result.extra["last_plan"] = Plan.model_validate(output)
        elif capability_id == "discover_assets":
            dumped = DiscoverAssetsOutput.model_validate(output)
            result.catalogue = MetadataCatalog.from_assets(dumped.snapshot_id, dumped.assets)
        elif capability_id == "describe_asset":
            result.descriptions.append(DescribeAssetOutput.model_validate(output))
        elif capability_id == "profile_estate":
            profiled = ProfileEstateOutput.model_validate(output)
            result.profiling = profiled
            result.profiling_run = ProfilingRunResult.model_validate(profiled.run_payload)
        elif capability_id == "propose_model_design":
            result.model_design = _align_invoice_status(
                ModelDesign.model_validate(output), result.fixture_version
            )
        elif capability_id == "generate_transformation":
            result.generated = GenerateTransformationOutput.model_validate(output)
        elif capability_id == "create_transformation":
            created = CreateTransformationOutput.model_validate(output)
            result.project_state_id = created.project_state_id
        elif capability_id == "parse_transformation":
            result.parse_ok = ParseTransformationOutput.model_validate(output).ok
            if not result.parse_ok:
                result.failed = True
                result.fail_reason = "PARSE_FAILED"
        elif capability_id == "compile_transformation":
            result.compile_ok = CompileTransformationOutput.model_validate(output).ok
            if not result.compile_ok:
                result.failed = True
                result.fail_reason = "COMPILE_FAILED"
        elif capability_id == "load_manifest_sources":
            result.load_ok = LoadManifestSourcesOutput.model_validate(output).reconcile_ok
            if not result.load_ok:
                result.failed = True
                result.fail_reason = "LOAD_FAILED"
        elif capability_id == "execute_transformation":
            result.execute_ok = ExecuteTransformationOutput.model_validate(output).ok
            if not result.execute_ok:
                result.failed = True
                result.fail_reason = "EXECUTE_FAILED"
        elif capability_id == "run_tests":
            result.tests_ok = RunTestsOutput.model_validate(output).ok
            if not result.tests_ok:
                result.failed = True
                result.fail_reason = "TESTS_FAILED"
        elif capability_id == "validate_interview_quality":
            result.quality = ValidationReport.model_validate(output)
            if not result.quality.passed:
                result.failed = True
                result.fail_reason = "QUALITY_FAILED"

    async def _store_artifact(
        self, workflow_id: UUID, artifact_type: str, body: dict[str, Any], *, capability_id: str
    ) -> None:
        digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        provenance = ArtifactProvenance(
            execution_mode=self._execution_mode,
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

    async def _finalize_status(self, result: InterviewResult) -> InterviewResult:
        async with self._sessions() as session:
            workflow = await session.get(WorkflowModel, result.workflow_id)
            assert workflow is not None
            result.events = tuple(
                item.event_type for item in self._events.history(result.workflow_id)
            )
            result.extra["workflow_state"] = workflow.state
        return result

    def _snapshot(self) -> ContractSnapshot:
        contracts = [
            CapabilityContractRef(
                capability_id=spec.id,
                capability_contract_version=1,
                input_schema_version=1,
                output_schema_version=1,
            )
            for spec in self._capabilities.all_specs()
            if spec.id in INTERVIEW_CAPABILITIES
        ]
        versions = {
            spec.connector_id: spec.version
            for spec in self._connectors.all_specs()
            if spec.connector_id in {"snowflake_ro", "snowflake_dev", "dbt_dev"}
        }
        return ContractSnapshot(
            snapshot_id=uuid4(),
            capability_contracts=tuple(contracts),
            connector_versions=versions,
        )


def plan_phase_handler(payload: BaseModel, _context: object) -> Plan:
    assert isinstance(payload, PlanPhaseInput)
    return plan_interview_phase(payload)


def generate_transformation_handler(
    payload: BaseModel, _context: object
) -> GenerateTransformationOutput:
    assert isinstance(payload, GenerateTransformationInput)
    return generate_vantara_transformation(payload)


def propose_model_design_handler(payload: BaseModel, _context: object) -> BaseModel:
    from aide.capabilities.io import ProposeModelDesignInput

    assert isinstance(payload, ProposeModelDesignInput)
    return propose_model_design(payload)


async def append_audit_outside(
    sessions: async_sessionmaker[AsyncSession],
    *,
    workflow_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    async with sessions() as session, session.begin():
        await append_audit_event(
            session, workflow_id=workflow_id, event_type=event_type, payload=payload
        )


def _evidence(run: ProfilingRunResult) -> tuple[Any, Any, Any, Any]:
    from aide.modelling.evidence import evidence_from_run

    return evidence_from_run(run)


def _align_invoice_status(design: ModelDesign, fixture_version: str) -> ModelDesign:
    """Map the accepted STATUS column onto v1 INVOICE_STATUS before validation."""
    if fixture_version != "v1":
        return design
    models = []
    for model in design.models:
        columns = []
        for column in model.columns:
            source = column.source_asset
            if (
                source is not None
                and source.address[-1] == "INVOICES"
                and (column.source_column or "").upper() == "STATUS"
            ):
                columns.append(column.model_copy(update={"source_column": "INVOICE_STATUS"}))
            else:
                columns.append(column)
        models.append(model.model_copy(update={"columns": tuple(columns)}))
    return design.model_copy(update={"models": tuple(models)})


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _ensure_legal(current: WorkflowState | str, target: WorkflowState) -> None:
    source = current if isinstance(current, WorkflowState) else WorkflowState(current)
    if (source, target) not in LEGAL_TRANSITIONS:
        raise RuntimeError(f"illegal transition {source.value} -> {target.value}")


def _planning_templates(
    workflow_id: UUID,
    snapshot_id: UUID,
    target_phase: WorkflowState,
    authorization: GrantAuthorization,
) -> tuple[TemplateSpec, ...]:
    payload = PlanPhaseInput(
        workflow_context_ref=str(workflow_id),
        phase=target_phase,
        contract_snapshot_ref=str(snapshot_id),
        capability_catalogue=(),
        constraints=PlanConstraints(
            max_tasks=50,
            effective_grants=tuple(sorted(item.value for item in authorization.effective)),
        ),
        occurrence="ENUMERATION",
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


def _discovery_templates(selected: tuple[AssetRef, ...]) -> tuple[TemplateSpec, ...]:
    templates: list[TemplateSpec] = [
        TemplateSpec(
            local_id="d_discover",
            capability_id="discover_assets",
            capability_contract_version=1,
            connector_id="snowflake_ro",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=60,
            max_attempts=2,
        )
    ]
    for asset in sorted(selected, key=lambda item: item.address):
        templates.append(
            TemplateSpec(
                local_id=f"d_{asset_slug(asset)}",
                capability_id="describe_asset",
                capability_contract_version=1,
                connector_id="snowflake_ro",
                depends_on=("d_discover",),
                required_dependencies=("d_discover",),
                unresolved_inputs=DescribeAssetInput(asset=asset).model_dump(mode="json"),
                timeout_seconds=60,
                max_attempts=2,
            )
        )
    return tuple(sorted(templates, key=lambda item: item.local_id))


def _profiling_templates(
    selected: tuple[AssetRef, ...], fixture_version: Literal["v1", "v2"]
) -> tuple[TemplateSpec, ...]:
    payload = ProfileEstateInput(assets=selected, fixture_version=fixture_version).model_dump(
        mode="json"
    )
    return (
        TemplateSpec(
            local_id="pr_estate",
            capability_id="profile_estate",
            capability_contract_version=1,
            connector_id="snowflake_ro",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs=payload,
            timeout_seconds=180,
            max_attempts=2,
        ),
    )


def _design_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="g2_propose_model_design",
            capability_id="propose_model_design",
            capability_contract_version=1,
            connector_id=None,
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=180,
            max_attempts=2,
        ),
    )


def _generation_templates() -> tuple[TemplateSpec, ...]:
    templates = (
        TemplateSpec(
            local_id="g_generate",
            capability_id="generate_transformation",
            capability_contract_version=1,
            connector_id=None,
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=120,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="g_create",
            capability_id="create_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("g_generate",),
            required_dependencies=("g_generate",),
            unresolved_inputs={},
            timeout_seconds=120,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="g_parse",
            capability_id="parse_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("g_create",),
            required_dependencies=("g_create",),
            unresolved_inputs={},
            timeout_seconds=120,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="g_compile",
            capability_id="compile_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("g_parse",),
            required_dependencies=("g_parse",),
            unresolved_inputs={},
            timeout_seconds=180,
            max_attempts=2,
        ),
    )
    return tuple(sorted(templates, key=lambda item: item.local_id))


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
            max_attempts=1,
        ),
    )


def _execution_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="e_load",
            capability_id="load_manifest_sources",
            capability_contract_version=1,
            connector_id="snowflake_dev",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=180,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="e_run",
            capability_id="execute_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("e_load",),
            required_dependencies=("e_load",),
            unresolved_inputs={},
            timeout_seconds=300,
            max_attempts=2,
        ),
    )


def _validation_templates() -> tuple[TemplateSpec, ...]:
    templates = (
        TemplateSpec(
            local_id="v1_tests",
            capability_id="run_tests",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=180,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="v2_quality",
            capability_id="validate_interview_quality",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("v1_tests",),
            required_dependencies=("v1_tests",),
            unresolved_inputs={},
            timeout_seconds=60,
            max_attempts=1,
        ),
    )
    return tuple(sorted(templates, key=lambda item: item.local_id))


__all__ = [
    "INTERVIEW_CAPABILITIES",
    "LEGAL_INTERVIEW_PHASES",
    "InterviewResult",
    "InterviewSupervisor",
    "generate_transformation_handler",
    "plan_phase_handler",
    "propose_model_design_handler",
]
