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
    classify_schema_mismatch,
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
    DetectSchemaDriftInput,
    DetectSchemaDriftOutput,
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
    TransformationFile,
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
from aide.domain.failures import FailureClass
from aide.domain.identity import canonical_json_bytes
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.repair import (
    ACCEPTED_ARTIFACT_PATH,
    ACCEPTED_ASSET_ADDRESS,
    ACCEPTED_FROM_COLUMN,
    ACCEPTED_TO_COLUMN,
    DriftEvidence,
    ProposeRepairInput,
    RepairApplication,
    RepairBudgetSnapshot,
    RepairEventKind,
    RepairProposal,
    RepairResult,
    RepairValidation,
    ValidateRepairInput,
)
from aide.domain.sql import AssetRef, SqlText
from aide.domain.states import (
    LEGAL_TRANSITIONS,
    TERMINAL_WORKFLOW_STATES,
    TaskState,
    WorkflowState,
)
from aide.domain.tasks import TaskTemplate
from aide.domain.twin import (
    EvidenceReference,
    SourceAuthorityRef,
    TwinAssetKind,
    TwinObservation,
    TwinObservationKind,
    TwinSnapshot,
)
from aide.domain.verification import (
    CostMetadata,
    EvidenceDigest,
    EvidenceSection,
    GatewayIntentRecord,
    PolicyDecisionRecord,
    TimingMetadata,
    VerifierEvidencePack,
    VerifierResult,
)
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
    acquire_workflow_lock,
    create_phase_occurrence,
    persist_materialized_task,
)
from aide.orchestration.worker import TaskClaim, claim_task, select_runnable_task
from aide.persistence.audit import append_audit_event
from aide.persistence.database import read_only_unit_of_work
from aide.persistence.gateway import GatewayDispatchRepository
from aide.persistence.models import (
    ArtifactModel,
    MaterializedTaskModel,
    PhaseRunModel,
    TaskTemplateModel,
    WorkflowModel,
)
from aide.persistence.repair import RepairEventRepository
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
from aide.repair.allowlist import is_accepted_authority
from aide.repair.budget import block_reason_for_action, snapshot_from_counts, snapshot_from_events
from aide.repair.diff import sha256_text
from aide.repair.drift import as_drift_column, build_drift_evidence
from aide.repair.inject import SchemaDriftInjector
from aide.repair.propose import propose_accepted_repair
from aide.repair.validate import validate_repair
from aide.repair.writer import patched_files
from aide.twin.capture import capture_snowflake_metadata
from aide.twin.context import (
    EstateAccessPolicy,
    EstateContextLimits,
    EstateContextRequest,
    assemble_estate_context,
)
from aide.twin.snapshot import build_twin_snapshot
from aide.verification.bundle import assemble_evidence_bundle
from aide.verification.evaluate import evaluate_verifier

OWNER = "mvp003-supervisor"
INTERVIEW_CAPABILITIES = frozenset(
    {
        "plan_phase",
        "discover_assets",
        "describe_asset",
        "detect_schema_drift",
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
        "propose_repair",
        "validate_repair",
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
    include_schema_drift: bool = False
    repair_stage: str | None = None
    failure_class: FailureClass | None = None
    drift: DriftEvidence | None = None
    proposal: RepairProposal | None = None
    repair_validation: RepairValidation | None = None
    repair_application: RepairApplication | None = None
    repair_result: RepairResult | None = None
    verifier: VerifierResult | None = None
    blocked: bool = False
    block_reason: str | None = None
    before_artifact_hash: str | None = None
    after_artifact_hash: str | None = None
    started_at: datetime | None = None
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
        drift_injector: SchemaDriftInjector | None = None,
    ) -> None:
        self._sessions = session_factory
        self._capabilities = capabilities
        self._connectors = connectors
        self._gateway = gateway
        self._events = events
        self._authorizer = GrantAuthorizer()
        self._execution_mode = execution_mode
        self._drift_injector = drift_injector

    async def run_customer_revenue(
        self,
        requirement_text: str,
        *,
        requested_grants: frozenset[PermissionLevel] | None = None,
        client_supplied_effective: frozenset[PermissionLevel] | None = None,
        principal: PrincipalRef | None = None,
        persist_bootstrap_session: bool = True,
        fixture_version: Literal["v1", "v2"] = "v1",
        include_schema_drift: bool = False,
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
            include_schema_drift=include_schema_drift,
            started_at=_naive(now),
            extra={"human_intervention_count": 0},
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
        if include_schema_drift:
            return await self._run_repair_and_verify(result, snapshot)
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
        result.extra["last_task_id"] = str(claim.task_id)
        if result.repair_stage:
            await self._refresh_durable_repair_budget(result, task_id=claim.task_id)
            action = _repair_budget_action(result, capability_id)
            if action is not None and await self._enforce_repair_budget(
                result, action=action, task_id=claim.task_id
            ):
                return True
        started = _naive(datetime.now(UTC))
        outcome = await self._gateway.execute(
            claim, principal=result.principal, authorization=result.grants
        )
        _record_capability_step(result, capability_id, started)
        if outcome.status == "RETRY_WAIT":
            result.extra["retry_count"] = int(result.extra.get("retry_count", 0)) + 1
        stopped = self._absorb_outcome(result, capability_id, outcome)
        if capability_id == "detect_schema_drift" and result.extra.get("last_detect") is not None:
            await self._record_drift(result)
        if capability_id == "propose_repair" and result.proposal is not None:
            await self._persist_repair_event(
                result,
                RepairEventKind.PROPOSAL,
                result.proposal.model_dump(mode="json"),
                task_id=claim.task_id,
            )
        if capability_id == "validate_repair" and result.repair_validation is not None:
            await self._persist_repair_event(
                result,
                RepairEventKind.VALIDATION,
                result.repair_validation.model_dump(mode="json"),
                reason_code=(
                    result.repair_validation.reason_codes[0]
                    if result.repair_validation.reason_codes
                    else None
                ),
                task_id=claim.task_id,
            )
        if (
            capability_id == "create_transformation"
            and result.repair_stage == "apply"
            and result.repair_application is not None
        ):
            await self._persist_repair_event(
                result,
                RepairEventKind.APPLICATION,
                result.repair_application.model_dump(mode="json"),
                task_id=claim.task_id,
            )
        if result.repair_stage:
            await self._refresh_durable_repair_budget(result, task_id=claim.task_id)
        return stopped

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
        if outcome.intent_id is not None:
            result.extra["last_intent_id"] = str(outcome.intent_id)
        self._absorb(result, capability_id, outcome.output)
        intents = result.extra.setdefault("intent_ids", [])
        if outcome.intent_id is not None:
            intents.append(str(outcome.intent_id))
            result.extra["last_intent_id"] = str(outcome.intent_id)
        evidence = result.extra.setdefault("evidence_ref_ids", [])
        if outcome.evidence_ref_id is not None:
            evidence.append(str(outcome.evidence_ref_id))
            result.extra.setdefault("evidence_by_capability", {})[capability_id] = str(
                outcome.evidence_ref_id
            )
        return result.failed or result.parked or result.blocked

    async def _materialize_ready(
        self, result: InterviewResult, *, phase_run_id: UUID, snapshot: ContractSnapshot
    ) -> None:
        del snapshot
        if result.repair_stage:
            await self._refresh_durable_repair_budget(result)
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
                workflow_id=result.workflow_id,
                model_design=result.model_design,
                fixture_version=result.fixture_version,
            ).model_dump(mode="json")
        if capability_id == "create_transformation":
            assert result.generated is not None
            files = result.generated.files
            if result.repair_stage == "apply":
                assert result.proposal is not None
                files = _repaired_project_files(result.generated.files, result.proposal)
            return CreateTransformationInput(
                files=files,
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
                fixture_version=result.fixture_version,
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
        if capability_id == "detect_schema_drift":
            described = _invoice_description(result)
            return DetectSchemaDriftInput(
                asset=described.asset,
                baseline_snapshot_id=described.snapshot_id,
                baseline_columns=described.columns,
            ).model_dump(mode="json")
        if capability_id == "propose_repair":
            return _propose_repair_payload(result).model_dump(mode="json")
        if capability_id == "validate_repair":
            return _validate_repair_payload(result).model_dump(mode="json")
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
            if result.repair_stage == "apply" and result.proposal is not None:
                written = next(
                    (
                        item
                        for item in created.written
                        if item.path == result.proposal.artifact_path
                    ),
                    created.written[0] if created.written else None,
                )
                result.repair_application = RepairApplication(
                    application_id=uuid4(),
                    proposal_id=result.proposal.proposal_id,
                    applied=True,
                    artifact_path=result.proposal.artifact_path,
                    preimage_sha256=result.proposal.preimage_sha256,
                    postimage_sha256=result.proposal.patched_sha256,
                    written_sha256=written.sha256 if written is not None else None,
                    gateway_intent_id=(
                        UUID(result.extra["last_intent_id"])
                        if result.extra.get("last_intent_id")
                        else None
                    ),
                    project_state_id=created.project_state_id,
                    applied_at=_naive(datetime.now(UTC)),
                )
        elif capability_id == "parse_transformation":
            result.parse_ok = ParseTransformationOutput.model_validate(output).ok
            if not result.parse_ok:
                if result.repair_stage:
                    result.blocked = True
                    result.block_reason = "STATIC_VALIDATION_FAILED"
                else:
                    result.failed = True
                    result.fail_reason = "PARSE_FAILED"
        elif capability_id == "compile_transformation":
            result.compile_ok = CompileTransformationOutput.model_validate(output).ok
            if not result.compile_ok:
                if result.repair_stage:
                    result.blocked = True
                    result.block_reason = "STATIC_VALIDATION_FAILED"
                else:
                    result.failed = True
                    result.fail_reason = "COMPILE_FAILED"
        elif capability_id == "load_manifest_sources":
            loaded = LoadManifestSourcesOutput.model_validate(output)
            result.load_ok = loaded.reconcile_ok
            result.extra["manifest_load"] = loaded
            if not result.load_ok:
                result.failed = True
                result.fail_reason = "LOAD_FAILED"
        elif capability_id == "execute_transformation":
            executed = ExecuteTransformationOutput.model_validate(output)
            result.execute_ok = executed.ok
            result.extra["last_execute"] = executed
            classified = classify_schema_mismatch(executed.results)
            if result.repair_stage == "diagnose":
                result.failure_class = classified
                if classified is not FailureClass.SCHEMA_MISMATCH:
                    result.blocked = True
                    result.block_reason = (
                        classified.value if classified is not None else "EXECUTE_FAILED"
                    )
            elif not executed.ok:
                result.failed = True
                result.fail_reason = "EXECUTE_FAILED"
        elif capability_id == "run_tests":
            tests = RunTestsOutput.model_validate(output)
            result.tests_ok = tests.ok
            result.extra["last_tests"] = tests
            if not result.tests_ok:
                if result.repair_stage:
                    result.blocked = True
                    result.block_reason = "POST_REPAIR_VALIDATION_FAILED"
                else:
                    result.failed = True
                    result.fail_reason = "TESTS_FAILED"
        elif capability_id == "validate_interview_quality":
            result.quality = ValidationReport.model_validate(output)
            if not result.quality.passed:
                if result.repair_stage:
                    result.blocked = True
                    result.block_reason = "POST_REPAIR_VALIDATION_FAILED"
                else:
                    result.failed = True
                    result.fail_reason = "QUALITY_FAILED"
        elif capability_id == "detect_schema_drift":
            result.extra["last_detect"] = DetectSchemaDriftOutput.model_validate(output)
        elif capability_id == "propose_repair":
            result.proposal = RepairProposal.model_validate(output)
            result.before_artifact_hash = result.proposal.preimage_sha256
            result.after_artifact_hash = result.proposal.patched_sha256
        elif capability_id == "validate_repair":
            result.repair_validation = RepairValidation.model_validate(output)
            if not result.repair_validation.allowed:
                result.blocked = True
                result.block_reason = (
                    result.repair_validation.reason_codes[0]
                    if result.repair_validation.reason_codes
                    else "BROADER_PARSED_DIFF"
                )

    async def _run_repair_and_verify(
        self, result: InterviewResult, snapshot: ContractSnapshot
    ) -> InterviewResult:
        result.extra["repair_started_at"] = _naive(datetime.now(UTC))
        try:
            return await self._run_repair_and_verify_body(result, snapshot)
        finally:
            started = result.extra.get("repair_started_at")
            if isinstance(started, datetime):
                result.extra["repair_duration_ms"] = max(
                    0, int((_naive(datetime.now(UTC)) - started).total_seconds() * 1000)
                )

    async def _run_repair_and_verify_body(
        self, result: InterviewResult, snapshot: ContractSnapshot
    ) -> InterviewResult:
        if self._drift_injector is None:
            result.failed = True
            result.fail_reason = "DRIFT_INJECTOR_MISSING"
            return await self._finalize_status(result)
        self._drift_injector.inject_invoice_status_rename(result.workflow_id)
        result.repair_stage = "diagnose"
        repair_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=repair_id,
                phase=WorkflowState.REPAIR,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_repair_diagnose_templates(),
                phase_exit_criteria=("schema_drift", "schema_mismatch"),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=repair_id, snapshot=snapshot):
            if result.blocked:
                return await self._block_repair(result)
            return await self._finalize_status(result)
        await self._persist_original_failure(result)
        if result.failure_class is not FailureClass.SCHEMA_MISMATCH:
            result.block_reason = result.block_reason or "FAILURE_CLASS_NOT_ALLOWED"
            return await self._block_repair(result)
        if result.drift is None or not result.drift.authoritative:
            result.block_reason = "MISSING_DRIFT_EVIDENCE"
            return await self._block_repair(result)
        await self._append_templates(repair_id, _repair_propose_templates())
        if await self._run_phase(result, phase_run_id=repair_id, snapshot=snapshot):
            if result.blocked:
                return await self._block_repair(result)
            return await self._finalize_status(result)
        if result.repair_validation is None or not result.repair_validation.allowed:
            result.block_reason = result.block_reason or "BROADER_PARSED_DIFF"
            return await self._block_repair(result)
        result.repair_stage = "apply"
        await self._append_templates(repair_id, _repair_apply_templates())
        if await self._run_phase(result, phase_run_id=repair_id, snapshot=snapshot):
            if result.blocked:
                return await self._block_repair(result)
            return await self._finalize_status(result)
        result.repair_stage = "post_validate"
        if await self._enforce_repair_budget(result, action="revalidate"):
            return await self._block_repair(result)
        execution_id = uuid4()
        if await self._advance(
            result,
            snapshot,
            NextPhase(
                phase_run_id=execution_id,
                phase=WorkflowState.EXECUTION,
                contract_snapshot_id=snapshot.snapshot_id,
                templates=_post_repair_execution_templates(),
                phase_exit_criteria=("post_repair_execution",),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=execution_id, snapshot=snapshot):
            if result.blocked:
                return await self._block_repair(result)
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
                phase_exit_criteria=("post_repair_tests", "post_repair_quality"),
            ),
        ):
            return await self._finalize_status(result)
        if await self._run_phase(result, phase_run_id=validation_id, snapshot=snapshot):
            if result.blocked:
                return await self._block_repair(result)
            return await self._finalize_status(result)
        await self._persist_repair_event(
            result,
            RepairEventKind.REVALIDATION,
            {
                "tests_ok": result.tests_ok,
                "quality_passed": result.quality.passed if result.quality else False,
            },
        )
        await self._refresh_durable_repair_budget(result)
        await self._run_verifier(result)
        if result.blocked:
            return await self._block_repair(result)
        result.repair_result = RepairResult(
            workflow_id=result.workflow_id,
            failure_class=result.failure_class,
            blocked=result.blocked,
            block_reason=result.block_reason,
            proposal=result.proposal,
            validation=result.repair_validation,
            application=result.repair_application,
            proposal_count=int(result.extra.get("proposal_count", 0)),
            applied_count=int(result.extra.get("applied_count", 0)),
            post_repair_revalidation_count=int(
                result.extra.get("post_repair_revalidation_count", 0)
            ),
        )
        await self._reduce_current(result)
        return await self._finalize_status(result)

    async def _append_templates(
        self, phase_run_id: UUID, templates: tuple[TemplateSpec, ...]
    ) -> None:
        async with self._sessions() as session, session.begin():
            for item in templates:
                session.add(
                    TaskTemplateModel(
                        phase_run_id=phase_run_id,
                        local_id=item.local_id,
                        capability_id=item.capability_id,
                        capability_contract_version=item.capability_contract_version,
                        connector_id=item.connector_id,
                        depends_on=list(item.depends_on),
                        required_dependencies=list(item.required_dependencies),
                        unresolved_inputs=item.unresolved_inputs,
                        timeout_seconds=item.timeout_seconds,
                        max_attempts=item.max_attempts,
                        created_by=item.created_by,
                    )
                )

    async def _record_drift(self, result: InterviewResult) -> None:
        detect = result.extra.get("last_detect")
        if not isinstance(detect, DetectSchemaDriftOutput):
            return
        described = _invoice_description(result)
        current_columns = _current_columns(described.columns, detect)
        now = _naive(datetime.now(UTC))
        authority = SourceAuthorityRef(
            authority_id="snowflake_ro",
            contract_version=self._connectors.get("snowflake_ro").version,
            scope=("VANTARA_RAW",),
        )
        drift = build_drift_evidence(
            asset=described.asset,
            detect=detect,
            current_columns=current_columns,
            baseline_columns=described.columns,
            source_authority=authority,
            observed_at=now,
            fresh_until=now + timedelta(hours=1),
            twin_snapshot_id=result.twin_snapshot.twin_snapshot_id
            if result.twin_snapshot is not None
            else uuid4(),
            execution_mode=self._execution_mode,
            producer_operation_key=None,
            from_column=ACCEPTED_FROM_COLUMN,
            to_column=ACCEPTED_TO_COLUMN,
        )
        evidence = EvidenceReference(
            evidence_ref_id=drift.evidence_ref_id,
            evidence_type="schema_drift",
            media_type="application/json",
            sha256=drift.sha256,
            size_bytes=len(canonical_json_bytes(drift.model_dump(mode="json"))),
            execution_mode=self._execution_mode,
            source_authority=authority,
            producer_operation_key=drift.sha256,
            created_at=now,
        )
        async with self._sessions() as session, session.begin():
            twins = TwinRepository(session)
            await twins.add_evidence_reference(evidence)
            records = await twins.pinned_snapshot(result.workflow_id)
            subject = next(
                (
                    item
                    for item in records.assets
                    if tuple(part.upper() for part in item.canonical_locator[:3])
                    == ACCEPTED_ASSET_ADDRESS
                    and item.kind is TwinAssetKind.DATASET
                ),
                None,
            )
            if subject is None:
                raise RuntimeError("pinned TwinSnapshot is missing the invoice dataset")
            observation = TwinObservation(
                observation_id=drift.observation_id,
                subject_asset_id=subject.asset_id,
                kind=TwinObservationKind.DRIFT,
                source_authority=authority,
                value={
                    "from_column": drift.from_column,
                    "to_column": drift.to_column,
                    "added": [item.model_dump(mode="json") for item in drift.added],
                    "removed": [item.model_dump(mode="json") for item in drift.removed],
                    "authoritative": drift.authoritative,
                },
                observed_at=now,
                fresh_until=drift.fresh_until,
                confidence=1.0,
                evidence_ref_id=evidence.evidence_ref_id,
            )
            await twins.add_observation(observation)
        result.drift = drift.model_copy(
            update={
                "producer_operation_key": drift.sha256,
                "twin_snapshot_id": drift.twin_snapshot_id,
            }
        )
        result.extra.setdefault("typed_evidence", {})["schema_drift"] = {
            "evidence_ref_id": str(evidence.evidence_ref_id),
            "sha256": drift.sha256,
        }

    async def _persist_original_failure(self, result: InterviewResult) -> None:
        executed = result.extra.get("last_execute")
        body = (
            executed.model_dump(mode="json")
            if isinstance(executed, ExecuteTransformationOutput)
            else {
                "ok": False,
                "failure_class": (result.failure_class.value if result.failure_class else None),
            }
        )
        await self._store_typed_evidence(
            result, "original_failure", body, capability_id="execute_transformation"
        )

    async def _persist_repair_event(
        self,
        result: InterviewResult,
        kind: RepairEventKind,
        payload: dict[str, Any],
        *,
        reason_code: str | None = None,
        task_id: UUID | None = None,
    ) -> None:
        resolved_task = task_id or _uuid_or_none(result.extra.get("last_task_id"))
        async with self._sessions() as session, session.begin():
            await RepairEventRepository(session).add(
                workflow_id=result.workflow_id,
                event_kind=kind,
                payload=payload,
                reason_code=reason_code,
                task_id=resolved_task,
            )

    async def _refresh_durable_repair_budget(
        self, result: InterviewResult, *, task_id: UUID | None = None
    ) -> RepairBudgetSnapshot:
        resolved_task = task_id or _uuid_or_none(result.extra.get("last_task_id"))
        async with self._sessions() as session:
            events = await RepairEventRepository(session).list_for_workflow(result.workflow_id)
        snapshot = snapshot_from_events(events, task_id=resolved_task)
        result.extra["proposal_count"] = snapshot.proposal_count
        result.extra["applied_count"] = snapshot.applied_count
        result.extra["applied_count_for_task"] = snapshot.applied_count_for_task
        result.extra["post_repair_revalidation_count"] = snapshot.post_repair_revalidation_count
        result.extra["repair_budget_source"] = "persisted_events"
        return snapshot

    async def _enforce_repair_budget(
        self,
        result: InterviewResult,
        *,
        action: str,
        task_id: UUID | None = None,
    ) -> bool:
        snapshot = await self._refresh_durable_repair_budget(result, task_id=task_id)
        reason = block_reason_for_action(snapshot, action)
        if reason is None:
            return False
        result.blocked = True
        result.block_reason = reason
        return True

    async def _block_repair(self, result: InterviewResult) -> InterviewResult:
        await self._refresh_durable_repair_budget(result)
        reason = result.block_reason or "REPAIR_BLOCKED"
        result.blocked = True
        result.block_reason = reason
        result.repair_result = RepairResult(
            workflow_id=result.workflow_id,
            failure_class=result.failure_class,
            blocked=True,
            block_reason=reason,
            proposal=result.proposal,
            validation=result.repair_validation,
            application=result.repair_application,
            proposal_count=int(result.extra.get("proposal_count", 0)),
            applied_count=int(result.extra.get("applied_count", 0)),
            post_repair_revalidation_count=int(
                result.extra.get("post_repair_revalidation_count", 0)
            ),
        )
        async with self._sessions() as session, session.begin():
            workflow = await session.get(WorkflowModel, result.workflow_id)
            assert workflow is not None
            workflow.blocked_from_phase = workflow.state
            workflow.state = WorkflowState.BLOCKED.value
            workflow.version += 1
            await RepairEventRepository(session).add(
                workflow_id=result.workflow_id,
                event_kind=RepairEventKind.BLOCK,
                payload={"reason": reason},
                reason_code=reason,
                task_id=_uuid_or_none(result.extra.get("last_task_id")),
            )
            await append_audit_event(
                session,
                workflow_id=result.workflow_id,
                event_type="WORKFLOW_BLOCKED",
                payload={"reason": reason, "phase": "REPAIR"},
            )
        return await self._finalize_status(result)

    async def _store_typed_evidence(
        self,
        result: InterviewResult,
        evidence_type: str,
        body: dict[str, Any],
        *,
        capability_id: str,
    ) -> EvidenceReference:
        digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        now = _naive(datetime.now(UTC))
        async with self._sessions() as session, session.begin():
            artifacts = ArtifactRepository(session)
            version = await artifacts.next_version(result.workflow_id, evidence_type)
            provenance = ArtifactProvenance(
                execution_mode=self._execution_mode,
                connector_id=None,
                connector_version=None,
                capability_id=capability_id,
                capability_version=1,
                operation_idempotency_key=digest,
                resolved_input_digest=digest,
            )
            artifact = await artifacts.add(
                workflow_id=result.workflow_id,
                task_id=None,
                artifact_type=evidence_type,
                version=version,
                schema_version=1,
                sha256=digest,
                provenance=provenance,
                body=body,
            )
            reference = EvidenceReference(
                evidence_ref_id=uuid4(),
                evidence_type=evidence_type,
                artifact_id=artifact.artifact_id,
                media_type="application/json",
                sha256=digest,
                size_bytes=len(canonical_json_bytes(body)),
                execution_mode=self._execution_mode,
                source_authority=SourceAuthorityRef(
                    authority_id="supervisor",
                    contract_version="1.0.0",
                    scope=("DEVELOPMENT",),
                ),
                producer_operation_key=digest,
                created_at=now,
            )
            await TwinRepository(session).add_evidence_reference(reference)
        stored = result.extra.setdefault("typed_evidence", {})
        stored[evidence_type] = {
            "evidence_ref_id": str(reference.evidence_ref_id),
            "sha256": digest,
        }
        return reference

    async def _run_verifier(self, result: InterviewResult) -> None:
        assert result.twin_snapshot is not None
        assert result.estate_context_sha256 is not None
        assert result.proposal is not None
        assert result.repair_validation is not None
        await self._store_typed_evidence(
            result,
            "repair_proposal",
            result.proposal.model_dump(mode="json"),
            capability_id="propose_repair",
        )
        await self._store_typed_evidence(
            result,
            "repair_validation",
            result.repair_validation.model_dump(mode="json"),
            capability_id="validate_repair",
        )
        if result.repair_application is not None:
            await self._store_typed_evidence(
                result,
                "repair_application",
                result.repair_application.model_dump(mode="json"),
                capability_id="create_transformation",
            )
        await self._store_typed_evidence(
            result,
            "dbt_parse",
            {"ok": result.parse_ok},
            capability_id="parse_transformation",
        )
        await self._store_typed_evidence(
            result,
            "dbt_compile",
            {"ok": result.compile_ok},
            capability_id="compile_transformation",
        )
        execute_body = (
            result.extra["last_execute"].model_dump(mode="json")
            if isinstance(result.extra.get("last_execute"), ExecuteTransformationOutput)
            else {"ok": result.execute_ok}
        )
        await self._store_typed_evidence(
            result, "dbt_execution", execute_body, capability_id="execute_transformation"
        )
        await self._store_typed_evidence(
            result, "dbt_tests", {"ok": result.tests_ok}, capability_id="run_tests"
        )
        quality_body = result.quality.model_dump(mode="json") if result.quality is not None else {}
        await self._store_typed_evidence(
            result, "quality_results", quality_body, capability_id="validate_interview_quality"
        )
        await self._store_typed_evidence(
            result,
            "post_repair_validation",
            {
                "tests_ok": result.tests_ok,
                "quality_passed": result.quality.passed if result.quality is not None else False,
                "execute_ok": result.execute_ok,
            },
            capability_id="validate_interview_quality",
        )
        if result.before_artifact_hash is not None:
            await self._store_typed_evidence(
                result,
                "before_artifact_hash",
                {"sha256": result.before_artifact_hash},
                capability_id="propose_repair",
            )
        if result.after_artifact_hash is not None:
            await self._store_typed_evidence(
                result,
                "after_artifact_hash",
                {"sha256": result.after_artifact_hash},
                capability_id="create_transformation",
            )
        pack = await self._verifier_pack(result)
        verdict = evaluate_verifier(pack)
        result.verifier = verdict
        await self._store_typed_evidence(
            result,
            "verifier_verdict",
            verdict.model_dump(mode="json"),
            capability_id="independent_verifier",
        )
        await self._persist_repair_event(
            result, RepairEventKind.VERDICT, verdict.model_dump(mode="json")
        )
        if verdict.verdict.value != "PASS":
            result.blocked = True
            result.block_reason = (
                verdict.reason_codes[0] if verdict.reason_codes else "VERIFIER_FAIL"
            )
        try:
            await self._persist_evidence_bundle(result, pack)
        except Exception as exc:
            result.failed = True
            result.fail_reason = "EVIDENCE_PERSISTENCE_FAILED"
            result.blocked = True
            result.block_reason = "EVIDENCE_PERSISTENCE_FAILED"
            result.extra["evidence_persist_error_type"] = type(exc).__name__

    async def _verifier_pack(self, result: InterviewResult) -> VerifierEvidencePack:
        assert result.twin_snapshot is not None
        assert result.estate_context_sha256 is not None
        typed = result.extra.get("typed_evidence", {})
        evidence: list[EvidenceDigest] = []
        bodies: dict[str, dict[str, Any]] = {}
        intents: tuple[Any, ...] = ()
        pinned_snapshot_id = result.twin_snapshot.twin_snapshot_id
        pinned_digest = result.twin_snapshot.manifest_sha256
        now = _naive(datetime.now(UTC))
        drift_evidence_ref_id: UUID | None = None
        drift_stale = True
        drift_authoritative = False
        async with read_only_unit_of_work(self._sessions) as session:
            intents = await GatewayDispatchRepository(session).list_for_workflow(result.workflow_id)
            pinned = await TwinRepository(session).pinned_snapshot(result.workflow_id)
            pinned_snapshot_id = pinned.snapshot.twin_snapshot_id
            pinned_digest = pinned.snapshot.manifest_sha256
            twins = TwinRepository(session)
            for name, payload in typed.items():
                reference = await twins.get_evidence_reference(UUID(payload["evidence_ref_id"]))
                if reference is None:
                    continue
                catalog_digest = payload.get("sha256")
                digest_mismatch = catalog_digest != reference.sha256
                claimed_sha256: str | None = None
                if reference.artifact_id is not None:
                    artifact = await session.get(ArtifactModel, reference.artifact_id)
                    if artifact is None:
                        digest_mismatch = True
                    else:
                        if artifact.sha256 != reference.sha256:
                            digest_mismatch = True
                        if artifact.body is not None:
                            actual = hashlib.sha256(canonical_json_bytes(artifact.body)).hexdigest()
                            if actual != artifact.sha256:
                                digest_mismatch = True
                            bodies[name] = artifact.body
                            claimed_sha256 = _claimed_content_hash(artifact.body)
                evidence.append(
                    EvidenceDigest(
                        evidence_ref_id=reference.evidence_ref_id,
                        evidence_type=name,
                        sha256=reference.sha256,
                        execution_mode=reference.execution_mode,
                        stale=False,
                        digest_mismatch=digest_mismatch,
                        claimed_sha256=claimed_sha256,
                        identity=(f"{name}:{reference.evidence_ref_id}:{reference.sha256}"),
                    )
                )
            invoice_ids = tuple(
                item.asset_id
                for item in pinned.assets
                if item.kind is TwinAssetKind.DATASET
                and tuple(part.upper() for part in item.canonical_locator[:3])
                == ACCEPTED_ASSET_ADDRESS
            )
            subject_ids = invoice_ids or tuple(item.asset_id for item in pinned.assets)
            observations = await twins.list_observations_by_kind(
                kind=TwinObservationKind.DRIFT, subject_asset_ids=subject_ids
            )
            observation = observations[0] if observations else None
            if observation is not None:
                drift_evidence_ref_id = observation.evidence_ref_id
                drift_stale = observation.fresh_until is not None and now > observation.fresh_until
                drift_authoritative = is_accepted_authority(
                    observation.source_authority.authority_id
                ) and bool(observation.value.get("authoritative", False))
        schema_drift_item = next(
            (item for item in evidence if item.evidence_type == "schema_drift"), None
        )
        if schema_drift_item is not None:
            evidence = [
                item.model_copy(update={"stale": drift_stale})
                if item.evidence_type == "schema_drift"
                else item
                for item in evidence
            ]
        result.extra["verifier_readonly"] = True
        gateway_records = tuple(
            GatewayIntentRecord(
                intent_id=item.intent_id,
                action=item.action,
                capability_id=item.capability_id,
                status=item.status,
                operation_idempotency_key=item.operation_idempotency_key,
                resolved_input_digest=item.resolved_input_digest,
                result_digest=item.result_digest,
                evidence_ref_id=item.evidence_ref_id,
                approval_id=item.approval_id,
                reconciled=item.status == "SUCCEEDED" and item.completed_at is not None,
            )
            for item in intents
        )
        policy_records = tuple(
            PolicyDecisionRecord(
                decision=str(item.policy_decision.get("decision", "ALLOW")),
                routing=str(item.policy_decision.get("routing", "EXECUTE")),
                reasons=tuple(item.policy_decision.get("reasons", ())),
                approval_required=item.policy_decision.get("decision") == "REQUIRE_APPROVAL",
                approved=item.approval_id is not None
                or item.policy_decision.get("decision") != "REQUIRE_APPROVAL",
            )
            for item in intents
        )
        quality_passed = result.quality.passed if result.quality is not None else False
        recon_passed = False
        if result.quality is not None:
            ids = {item.check_id: item.passed for item in result.quality.checks}
            recon_passed = ids.get("invoice_line_sum_matches_mart", False) and ids.get(
                "payment_sum_matches_mart", False
            )
        started = result.started_at or _naive(datetime.now(UTC))
        wall_ms = max(0, int((_naive(datetime.now(UTC)) - started).total_seconds() * 1000))
        plan = result.extra.get("last_plan")
        plan_digest = (
            hashlib.sha256(canonical_json_bytes(plan.model_dump(mode="json"))).hexdigest()
            if isinstance(plan, Plan)
            else hashlib.sha256(b"plan").hexdigest()
        )
        proposal_body = bodies.get("repair_proposal")
        application_body = bodies.get("repair_application")
        before_hash = _sha_field(proposal_body, "preimage_sha256")
        after_hash = _sha_field(application_body, "postimage_sha256") or _sha_field(
            proposal_body, "patched_sha256"
        )
        repair_in_scope = bool(
            proposal_body is not None
            and proposal_body.get("from_column") == ACCEPTED_FROM_COLUMN
            and proposal_body.get("to_column") == ACCEPTED_TO_COLUMN
        )
        if proposal_body is None and result.proposal is not None:
            repair_in_scope = (
                result.proposal.from_column == ACCEPTED_FROM_COLUMN
                and result.proposal.to_column == ACCEPTED_TO_COLUMN
            )
        repair_applied = bool(application_body and application_body.get("applied"))
        if application_body is None:
            repair_applied = bool(result.repair_application and result.repair_application.applied)
        return VerifierEvidencePack(
            workflow_id=result.workflow_id,
            twin_snapshot_id=pinned_snapshot_id,
            estate_context_sha256=result.estate_context_sha256,
            pinned_snapshot_digest=pinned_digest,
            claimed_snapshot_id=result.twin_snapshot.twin_snapshot_id,
            claimed_estate_context_sha256=result.estate_context_sha256,
            business_request="Build a customer revenue analytical data product",
            plan_digest=plan_digest,
            policy_decisions=policy_records,
            risk_decisions=tuple(str(item.risk_decision.get("risk", "LOW")) for item in intents),
            gateway_intents=gateway_records,
            evidence=tuple(evidence),
            quality_passed=quality_passed,
            revenue_reconciliation_passed=recon_passed,
            failure_class=result.failure_class.value if result.failure_class else None,
            drift_evidence_ref_id=drift_evidence_ref_id,
            drift_stale=drift_stale,
            drift_authoritative=drift_authoritative,
            before_artifact_hash=before_hash,
            after_artifact_hash=after_hash,
            repair_in_scope=repair_in_scope,
            repair_applied=repair_applied,
            post_repair_validation_passed=result.tests_ok and quality_passed and result.execute_ok,
            require_real_chain=self._execution_mode is ExecutionMode.REAL,
            timing=TimingMetadata(
                wall_time_ms=wall_ms,
                step_durations_ms=tuple(
                    (str(name), int(ms)) for name, ms in result.extra.get("step_durations_ms", [])
                ),
                snowflake_query_ms=None,
                snowflake_timing_measured=False,
                dbt_timing_ms=_dbt_step_ms(result),
                dbt_timing_measured=_dbt_step_ms(result) is not None,
                retry_count=int(result.extra.get("retry_count", 0)),
                repair_count=int(result.extra.get("applied_count", 0)),
            ),
            cost=CostMetadata(
                model_tokens=None,
                model_cost_usd=None,
                warehouse_credits=None,
                measured=False,
                estimated=True,
            ),
        )

    async def _persist_evidence_bundle(
        self, result: InterviewResult, pack: VerifierEvidencePack
    ) -> None:
        typed = result.extra.get("typed_evidence", {})
        required_names = {
            "request",
            "twin_snapshot",
            "estate_context",
            "plan",
            "policy_decisions",
            "risk_decisions",
            "gateway_intents",
            "attempts",
            "reconciliation",
            "dbt_artifacts",
            "quality_results",
            "revenue_payment_reconciliation",
            "original_failure",
            "schema_drift",
            "repair_proposal",
            "repair_validation",
            "before_artifact_hash",
            "approved_parsed_diff",
            "repair_application",
            "after_artifact_hash",
            "dbt_parse",
            "dbt_compile",
            "dbt_execution",
            "dbt_tests",
            "post_repair_validation",
            "twin_observations",
            "verifier_verdict",
            "timing_metadata",
            "cost_metadata",
        }
        extras = {
            "request": result.requirement.model_dump(mode="json") if result.requirement else {},
            "twin_snapshot": {
                "twin_snapshot_id": str(result.twin_snapshot.twin_snapshot_id)
                if result.twin_snapshot
                else None
            },
            "estate_context": {"sha256": result.estate_context_sha256},
            "plan": pack.plan_digest,
            "policy_decisions": [item.model_dump(mode="json") for item in pack.policy_decisions],
            "risk_decisions": list(pack.risk_decisions),
            "gateway_intents": [item.model_dump(mode="json") for item in pack.gateway_intents],
            "attempts": {"count": len(pack.gateway_intents)},
            "reconciliation": {"reconciled": all(item.reconciled for item in pack.gateway_intents)},
            "dbt_artifacts": {"parse": result.parse_ok, "compile": result.compile_ok},
            "revenue_payment_reconciliation": {"passed": pack.revenue_reconciliation_passed},
            "approved_parsed_diff": result.repair_validation.parsed_diff.model_dump(mode="json")
            if result.repair_validation
            else {},
            "twin_observations": {
                "drift": result.drift.model_dump(mode="json") if result.drift else None
            },
            "timing_metadata": pack.timing.model_dump(mode="json"),
            "cost_metadata": pack.cost.model_dump(mode="json"),
        }
        for name, body in extras.items():
            if name not in typed:
                payload = body if isinstance(body, dict) else {"value": body}
                await self._store_typed_evidence(result, name, payload, capability_id="supervisor")
        typed = result.extra.get("typed_evidence", {})
        sections = []
        for name in sorted(required_names):
            payload = typed[name]
            sections.append(
                EvidenceSection(
                    name=name,
                    evidence_ref_id=UUID(payload["evidence_ref_id"]),
                    sha256=payload["sha256"],
                    execution_mode=self._execution_mode,
                )
            )
        assert result.twin_snapshot is not None
        assert result.estate_context_sha256 is not None
        bundle = assemble_evidence_bundle(
            workflow_id=result.workflow_id,
            twin_snapshot_id=result.twin_snapshot.twin_snapshot_id,
            estate_context_sha256=result.estate_context_sha256,
            sections=tuple(sections),
        )
        await self._store_typed_evidence(
            result, "evidence_bundle", bundle.model_dump(mode="json"), capability_id="supervisor"
        )
        result.extra["evidence_bundle_sha256"] = bundle.bundle_sha256

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
        now = _naive(datetime.now(UTC))
        result.extra.setdefault("human_intervention_count", 0)
        async with self._sessions() as session, session.begin():
            await acquire_workflow_lock(session, result.workflow_id)
            workflow = await session.get(WorkflowModel, result.workflow_id)
            assert workflow is not None
            current = WorkflowState(workflow.state)
            target: WorkflowState | None = None
            if current not in TERMINAL_WORKFLOW_STATES:
                if result.blocked or result.parked:
                    if current is not WorkflowState.BLOCKED:
                        target = WorkflowState.BLOCKED
                elif result.failed:
                    target = WorkflowState.FAILED
            if target is not None:
                _ensure_legal(current, target)
                if target is WorkflowState.BLOCKED and workflow.blocked_from_phase is None:
                    workflow.blocked_from_phase = workflow.state
                workflow.state = target.value
                if target is WorkflowState.FAILED:
                    workflow.finished_at = now
                workflow.version += 1
                await append_audit_event(
                    session,
                    workflow_id=result.workflow_id,
                    event_type=(
                        "WORKFLOW_FAILED" if target is WorkflowState.FAILED else "WORKFLOW_BLOCKED"
                    ),
                    payload={
                        "reason": result.fail_reason or result.block_reason or result.park_reason,
                        "from_state": current.value,
                    },
                )
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


def _invoice_description(result: InterviewResult) -> DescribeAssetOutput:
    for item in result.descriptions:
        address = tuple(part.upper() for part in item.asset.address[:3])
        if address == ACCEPTED_ASSET_ADDRESS:
            return item
    raise RuntimeError("invoice description is missing from discovery")


def _invoice_sql(result: InterviewResult) -> str:
    assert result.generated is not None
    for item in result.generated.files:
        if item.path == ACCEPTED_ARTIFACT_PATH:
            return item.content
    raise RuntimeError("generated invoice staging SQL is missing")


def _current_columns(baseline: tuple[Any, ...], detect: DetectSchemaDriftOutput) -> tuple[Any, ...]:
    removed = {item.name.upper() for item in detect.removed}
    kept = tuple(item for item in baseline if item.name.upper() not in removed)
    return kept + detect.added


def _propose_repair_payload(result: InterviewResult) -> ProposeRepairInput:
    described = _invoice_description(result)
    detect = result.extra.get("last_detect")
    if not isinstance(detect, DetectSchemaDriftOutput):
        raise RuntimeError("authoritative drift detect output is missing")
    assert result.drift is not None
    assert result.twin_snapshot is not None
    assert result.estate_context_sha256 is not None
    sql = _invoice_sql(result)
    current = _current_columns(described.columns, detect)
    return ProposeRepairInput(
        failure_class=result.failure_class or FailureClass.SCHEMA_MISMATCH,
        asset=described.asset,
        from_column=ACCEPTED_FROM_COLUMN,
        to_column=ACCEPTED_TO_COLUMN,
        old_data_type=result.drift.old_data_type,
        new_data_type=result.drift.new_data_type,
        added=tuple(as_drift_column(item) for item in detect.added),
        removed=tuple(as_drift_column(item) for item in detect.removed),
        current_columns=tuple(as_drift_column(item) for item in current),
        baseline_columns=tuple(as_drift_column(item) for item in described.columns),
        artifact_path=ACCEPTED_ARTIFACT_PATH,
        artifact_sql=sql,
        preimage_sha256=sha256_text(sql),
        twin_snapshot_id=result.twin_snapshot.twin_snapshot_id,
        estate_context_sha256=result.estate_context_sha256,
        drift_evidence_ref_id=result.drift.evidence_ref_id,
        source_authority=result.drift.source_authority,
    )


def _validate_repair_payload(result: InterviewResult) -> ValidateRepairInput:
    assert result.proposal is not None
    assert result.drift is not None
    assert result.generated is not None
    if result.extra.get("repair_budget_source") != "persisted_events":
        raise RuntimeError("repair budget must be loaded from persisted RepairEvent records")
    original_files = tuple((item.path, item.content, item.kind) for item in result.generated.files)
    return ValidateRepairInput(
        proposal=result.proposal,
        original_sql=_invoice_sql(result),
        original_files=original_files,
        drift=result.drift,
        budget=snapshot_from_counts(
            proposal_count=int(result.extra.get("proposal_count", 0)),
            applied_count=int(result.extra.get("applied_count", 0)),
            applied_count_for_task=int(result.extra.get("applied_count_for_task", 0)),
            post_repair_revalidation_count=int(
                result.extra.get("post_repair_revalidation_count", 0)
            ),
        ),
        now=_naive(datetime.now(UTC)),
        static_sql_ok=True,
    )


def _repaired_project_files(
    files: tuple[TransformationFile, ...], proposal: RepairProposal
) -> tuple[TransformationFile, ...]:
    patched = patched_files(proposal)[0]
    replaced: list[TransformationFile] = []
    for item in files:
        if item.path == proposal.artifact_path:
            replaced.append(
                TransformationFile(path=item.path, content=patched.content, kind=item.kind)
            )
        else:
            replaced.append(item)
    return tuple(replaced)


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


def propose_repair_handler(payload: BaseModel, _context: object) -> RepairProposal:
    assert isinstance(payload, ProposeRepairInput)
    return propose_accepted_repair(payload)


def validate_repair_handler(payload: BaseModel, _context: object) -> RepairValidation:
    assert isinstance(payload, ValidateRepairInput)
    return validate_repair(payload)


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


def _repair_budget_action(result: InterviewResult, capability_id: str) -> str | None:
    if capability_id == "propose_repair":
        return "propose"
    if capability_id == "create_transformation" and result.repair_stage == "apply":
        return "apply"
    return None


def _uuid_or_none(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value:
        return UUID(value)
    return None


def _hex_digest(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    if any(char not in "0123456789abcdef" for char in value):
        return None
    return value


def _claimed_content_hash(body: dict[str, Any] | None) -> str | None:
    if not isinstance(body, dict):
        return None
    return _hex_digest(body.get("sha256"))


def _sha_field(body: dict[str, Any] | None, field: str) -> str | None:
    if not isinstance(body, dict):
        return None
    return _hex_digest(body.get(field))


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


_DBT_STEP_NAMES = frozenset(
    {
        "create_transformation",
        "parse_transformation",
        "compile_transformation",
        "execute_transformation",
        "run_tests",
    }
)


def _record_capability_step(result: InterviewResult, capability_id: str, started: datetime) -> None:
    elapsed_ms = max(0, int((_naive(datetime.now(UTC)) - started).total_seconds() * 1000))
    steps = list(result.extra.get("step_durations_ms", []))
    steps.append((capability_id, elapsed_ms))
    result.extra["step_durations_ms"] = steps
    sequence = list(result.extra.get("capability_sequence", []))
    sequence.append(capability_id)
    result.extra["capability_sequence"] = sequence


def _dbt_step_ms(result: InterviewResult) -> int | None:
    total = 0
    found = False
    for name, ms in result.extra.get("step_durations_ms", []):
        if name in _DBT_STEP_NAMES:
            total += int(ms)
            found = True
    return total if found else None


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


def _repair_diagnose_templates() -> tuple[TemplateSpec, ...]:
    templates = (
        TemplateSpec(
            local_id="r_detect",
            capability_id="detect_schema_drift",
            capability_contract_version=1,
            connector_id="snowflake_ro",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=60,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="r_execute",
            capability_id="execute_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("r_detect",),
            required_dependencies=("r_detect",),
            unresolved_inputs={},
            timeout_seconds=300,
            max_attempts=2,
        ),
    )
    return tuple(sorted(templates, key=lambda item: item.local_id))


def _repair_propose_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="r_propose",
            capability_id="propose_repair",
            capability_contract_version=1,
            connector_id=None,
            depends_on=("r_execute",),
            required_dependencies=("r_execute",),
            unresolved_inputs={},
            timeout_seconds=30,
            max_attempts=1,
        ),
        TemplateSpec(
            local_id="r_validate",
            capability_id="validate_repair",
            capability_contract_version=1,
            connector_id=None,
            depends_on=("r_propose",),
            required_dependencies=("r_propose",),
            unresolved_inputs={},
            timeout_seconds=30,
            max_attempts=1,
        ),
    )


def _repair_apply_templates() -> tuple[TemplateSpec, ...]:
    templates = (
        TemplateSpec(
            local_id="r_apply",
            capability_id="create_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("r_validate",),
            required_dependencies=("r_validate",),
            unresolved_inputs={},
            timeout_seconds=120,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="r_parse",
            capability_id="parse_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("r_apply",),
            required_dependencies=("r_apply",),
            unresolved_inputs={},
            timeout_seconds=120,
            max_attempts=2,
        ),
        TemplateSpec(
            local_id="r_compile",
            capability_id="compile_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=("r_parse",),
            required_dependencies=("r_parse",),
            unresolved_inputs={},
            timeout_seconds=180,
            max_attempts=2,
        ),
    )
    return tuple(sorted(templates, key=lambda item: item.local_id))


def _post_repair_execution_templates() -> tuple[TemplateSpec, ...]:
    return (
        TemplateSpec(
            local_id="e_rerun",
            capability_id="execute_transformation",
            capability_contract_version=1,
            connector_id="dbt_dev",
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs={},
            timeout_seconds=300,
            max_attempts=2,
        ),
    )


__all__ = [
    "INTERVIEW_CAPABILITIES",
    "LEGAL_INTERVIEW_PHASES",
    "InterviewResult",
    "InterviewSupervisor",
    "generate_transformation_handler",
    "plan_phase_handler",
    "propose_model_design_handler",
    "propose_repair_handler",
    "validate_repair_handler",
]
