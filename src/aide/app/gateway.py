"""Governed Tool Gateway: the sole connector execution boundary.

Lifecycle: validate → principal/operation/capability → policy → persist risk →
approval bind → record dispatch intent and attempt → execute outside the
database transaction → canonicalize → reconcile ambiguous effects before retry
→ persist result and evidence → audit. External work is never held inside a
PostgreSQL transaction. Callers never receive a mutable vendor client.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.parking import fail_closed_task, park_task
from aide.capabilities.registry import CapabilityRegistry
from aide.capabilities.spec import CapabilitySpec
from aide.connectors.base.context import (
    AttemptRecoveryRef,
    CallContext,
    RecoveryContext,
    RedactionPolicy,
)
from aide.connectors.base.reconcile import EffectFound
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import ConnectorSpec
from aide.domain.artifacts import ExecutionMode
from aide.domain.effects import EffectSemantics
from aide.domain.enums import TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.identity import canonical_json_bytes
from aide.domain.principal import GrantAuthorization, PrincipalRef
from aide.domain.states import TaskState
from aide.domain.twin import EvidenceReference, SourceAuthorityRef
from aide.domain.versions import CapabilityContractRef
from aide.orchestration.recovery import apply_reconcile_result
from aide.orchestration.worker import (
    RecoveryClaim,
    TaskClaim,
    acquire_recovery,
    finalize_failure,
    finalize_success,
    mark_dispatched,
)
from aide.persistence.audit import append_audit_event
from aide.persistence.gateway import GatewayDispatchRepository
from aide.persistence.models import MaterializedTaskModel, PhaseRunModel
from aide.persistence.twin import TwinRepository
from aide.policy.engine import PolicyEngine
from aide.policy.request import PolicyDecision, PolicyRequest
from aide.tools.binding import ConnectorBinding
from aide.tools.registry import OutputInvalid

GatewayStatus = Literal[
    "SUCCEEDED",
    "FAILED",
    "PARKED",
    "STALE",
    "RETRY_WAIT",
    "RECOVERING",
]
GatewayAction = Literal["EXECUTE", "CANCEL", "RECONCILE"]
OWNER = "mvp002-gateway"
RECOVERY_LEASE = timedelta(seconds=60)
RECONCILE_DEADLINE = timedelta(seconds=30)
MAX_RECONCILE_CHECKS = 4


class GatewayOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: GatewayStatus
    output: BaseModel | None = None
    policy: PolicyDecision | None = None
    intent_id: UUID | None = None
    evidence_ref_id: UUID | None = None
    failure_classification: str | None = None
    task_state: str | None = None
    recovered: bool = False


@dataclass(frozen=True)
class _Prepared:
    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    capability_id: str
    connector_id: str | None
    connector_version: str | None
    operation_key: str
    input_digest: str
    spec: CapabilitySpec
    connector: ConnectorSpec | None
    binding: ConnectorBinding
    payload: BaseModel
    context: CallContext
    intent_id: UUID
    policy: PolicyDecision
    attempt_count: int


class GovernedToolGateway:
    """Canonical execute/cancel/reconcile path for every connector operation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        capabilities: CapabilityRegistry,
        connectors: ConnectorRegistry,
        policy: PolicyEngine | None = None,
        owner: str = OWNER,
        execution_mode: ExecutionMode = ExecutionMode.MOCK,
    ) -> None:
        self._sessions = session_factory
        self._capabilities = capabilities
        self._connectors = connectors
        self._policy = policy or PolicyEngine()
        self._owner = owner
        self._execution_mode = execution_mode
        self._bindings: dict[tuple[str | None, str], ConnectorBinding] = {}

    def register_binding(
        self,
        capability_id: str,
        binding: ConnectorBinding,
        *,
        connector_id: str | None = None,
    ) -> None:
        self._bindings[(connector_id, capability_id)] = binding

    def _binding_for(self, capability_id: str, connector_id: str | None) -> ConnectorBinding | None:
        found = self._bindings.get((connector_id, capability_id))
        if found is not None:
            return found
        return self._bindings.get((None, capability_id))

    async def execute(
        self,
        claim: TaskClaim,
        *,
        principal: PrincipalRef,
        authorization: GrantAuthorization,
        payload: BaseModel | dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> GatewayOutcome:
        instant = _naive(now or datetime.now(UTC))
        prepared = await self._prepare_dispatch(
            claim,
            action="EXECUTE",
            principal=principal,
            authorization=authorization,
            payload=payload,
            now=instant,
            mark_running=True,
        )
        if isinstance(prepared, GatewayOutcome):
            return prepared
        try:
            raw = await prepared.binding.execute(
                prepared.capability_id, prepared.payload, prepared.context
            )
        except Exception as exc:
            return await self._handle_execute_failure(
                claim,
                prepared,
                exc,
                instant,
                principal=principal,
                authorization=authorization,
            )
        return await self._persist_success(claim, prepared, raw, instant)

    async def cancel(
        self,
        claim: TaskClaim,
        *,
        principal: PrincipalRef,
        authorization: GrantAuthorization,
        now: datetime | None = None,
    ) -> GatewayOutcome:
        instant = _naive(now or datetime.now(UTC))
        prepared = await self._prepare_dispatch(
            claim,
            action="CANCEL",
            principal=principal,
            authorization=authorization,
            payload=None,
            now=instant,
            mark_running=False,
        )
        if isinstance(prepared, GatewayOutcome):
            return prepared
        try:
            await prepared.binding.cancel(prepared.capability_id, prepared.context)
        except Exception as exc:
            return await self._complete_failure(claim, prepared, _failure_class(exc), instant)
        return await self._complete_action(claim, prepared, "CANCEL", instant)

    async def reconcile(
        self,
        claim: RecoveryClaim,
        *,
        principal: PrincipalRef | None = None,
        authorization: GrantAuthorization | None = None,
        now: datetime | None = None,
    ) -> GatewayOutcome:
        del principal, authorization
        instant = _naive(now or datetime.now(UTC))
        async with self._sessions() as session, session.begin():
            task = await session.get(MaterializedTaskModel, claim.task_id)
            if task is None:
                raise LookupError("recovery task does not exist")
            spec = self._capabilities.get(task.capability_id, 1)
            binding = self._binding_for(task.capability_id, task.connector_id)
            if binding is None:
                await fail_closed_task(
                    session,
                    task_id=task.task_id,
                    reason="CONNECTOR_BINDING_MISSING",
                    now=instant,
                )
                return GatewayOutcome(
                    status="FAILED", failure_classification="CONNECTOR_BINDING_MISSING"
                )
            connector = (
                self._connectors.get(task.connector_id)
                if task.connector_id is not None and self._connectors.contains(task.connector_id)
                else None
            )
            intents = GatewayDispatchRepository(session)
            existing = await intents.get_by_attempt(claim.attempt_id, "RECONCILE")
            if existing is None:
                existing = await intents.record(
                    workflow_id=task.workflow_id,
                    phase_run_id=task.phase_run_id,
                    task_id=task.task_id,
                    attempt_id=claim.attempt_id,
                    action="RECONCILE",
                    capability_id=task.capability_id,
                    connector_id=task.connector_id,
                    connector_version=task.connector_version,
                    operation_idempotency_key=task.operation_idempotency_key,
                    resolved_input_digest=task.resolved_input_digest,
                    policy_decision={"decision": "ALLOW", "source": "recovery"},
                    risk_decision=_risk_decision(spec),
                    status="DISPATCHED",
                )
                await append_audit_event(
                    session,
                    workflow_id=task.workflow_id,
                    phase_run_id=task.phase_run_id,
                    task_id=task.task_id,
                    attempt_id=claim.attempt_id,
                    operation_idempotency_key=task.operation_idempotency_key,
                    event_type="GATEWAY_DISPATCH_INTENT",
                    payload={"action": "RECONCILE", "intent_id": str(existing.intent_id)},
                )
            intent_id = existing.intent_id
            recovery_ctx = _recovery_context(task, claim, spec, connector, instant)
            copies = (
                task.workflow_id,
                task.phase_run_id,
                task.operation_idempotency_key,
                task.connector_id,
                task.connector_version,
            )
        result = await binding.reconcile(recovery_ctx)
        return await self._apply_reconcile(claim, spec, result, intent_id, instant, copies)

    async def _prepare_dispatch(
        self,
        claim: TaskClaim,
        *,
        action: GatewayAction,
        principal: PrincipalRef,
        authorization: GrantAuthorization,
        payload: BaseModel | dict[str, Any] | None,
        now: datetime,
        mark_running: bool,
    ) -> _Prepared | GatewayOutcome:
        async with self._sessions() as session, session.begin():
            task = await session.get(MaterializedTaskModel, claim.task_id)
            if task is None:
                raise LookupError("claimed task does not exist")
            spec = self._capabilities.get(task.capability_id, 1)
            binding = self._binding_for(task.capability_id, task.connector_id)
            if binding is None:
                await fail_closed_task(
                    session,
                    task_id=task.task_id,
                    reason="CONNECTOR_BINDING_MISSING",
                    now=now,
                )
                return GatewayOutcome(
                    status="FAILED", failure_classification="CONNECTOR_BINDING_MISSING"
                )
            connector: ConnectorSpec | None = None
            registered = True
            advertises = True
            if task.connector_id is not None:
                registered = self._connectors.contains(task.connector_id)
                if registered:
                    connector = self._connectors.get(task.connector_id)
                    advertises = connector.advertises(spec.id, spec.version)
            raw_payload = payload if payload is not None else task.resolved_inputs
            try:
                validated = (
                    raw_payload
                    if isinstance(raw_payload, spec.input_schema)
                    else spec.input_schema.model_validate(raw_payload)
                )
            except ValidationError:
                await fail_closed_task(
                    session,
                    task_id=task.task_id,
                    reason="INPUT_INVALID",
                    now=now,
                )
                return GatewayOutcome(status="FAILED", failure_classification="INPUT_INVALID")
            phase = await session.get(PhaseRunModel, task.phase_run_id)
            snapshot_id = phase.contract_snapshot_id if phase is not None else uuid4()
            health = await binding.health()
            request = PolicyRequest(
                workflow_id=task.workflow_id,
                phase_run_id=task.phase_run_id,
                task_id=task.task_id,
                operation_idempotency_key=task.operation_idempotency_key,
                resolved_input_digest=task.resolved_input_digest,
                contract_snapshot_id=snapshot_id,
                principal=principal,
                grant_authorization=authorization,
                capability=spec,
                connector=connector,
                connector_health=health,
                target_environment=connector.target_environment if connector is not None else None,
                workflow_grants=authorization.effective,
                evaluated_at=now,
                approval_expires_at=now + timedelta(hours=1),
                capability_known=True,
                connector_registered=registered,
                connector_advertises_capability=advertises,
            )
            decision = self._policy.evaluate(request)
            if decision.routing == "PARK":
                reason = decision.reasons[0].value if decision.reasons else "PARKED"
                await park_task(
                    session,
                    task_id=task.task_id,
                    reason=reason,
                    now=now,
                    routing=decision.routing,
                    reasons=tuple(item.value for item in decision.reasons),
                )
                return GatewayOutcome(
                    status="PARKED", policy=decision, failure_classification=reason
                )
            if decision.decision != "ALLOW":
                reason = decision.reasons[0].value if decision.reasons else "DENIED"
                await fail_closed_task(
                    session,
                    task_id=task.task_id,
                    reason=reason,
                    now=now,
                    routing=decision.routing,
                    reasons=tuple(item.value for item in decision.reasons),
                )
                return GatewayOutcome(
                    status="FAILED", policy=decision, failure_classification=reason
                )
            intents = GatewayDispatchRepository(session)
            existing = await intents.get_by_attempt(claim.attempt_id, action)
            if existing is None:
                existing = await intents.record(
                    workflow_id=task.workflow_id,
                    phase_run_id=task.phase_run_id,
                    task_id=task.task_id,
                    attempt_id=claim.attempt_id,
                    action=action,
                    capability_id=task.capability_id,
                    connector_id=task.connector_id,
                    connector_version=task.connector_version,
                    operation_idempotency_key=task.operation_idempotency_key,
                    resolved_input_digest=task.resolved_input_digest,
                    policy_decision=decision.model_dump(mode="json"),
                    risk_decision=_risk_decision(spec),
                    status="DISPATCHED",
                )
            if mark_running:
                dispatched = await mark_dispatched(session, claim)
                if not dispatched:
                    raise RuntimeError("lost claim before governed dispatch")
            await append_audit_event(
                session,
                workflow_id=task.workflow_id,
                phase_run_id=task.phase_run_id,
                task_id=task.task_id,
                attempt_id=claim.attempt_id,
                operation_idempotency_key=task.operation_idempotency_key,
                event_type="GATEWAY_DISPATCH_INTENT",
                payload={
                    "action": action,
                    "intent_id": str(existing.intent_id),
                    "capability_id": task.capability_id,
                    "connector_id": task.connector_id,
                },
            )
            context = CallContext(
                workflow_id=task.workflow_id,
                phase_run_id=task.phase_run_id,
                task_id=task.task_id,
                operation_idempotency_key=task.operation_idempotency_key,
                resolved_input_digest=task.resolved_input_digest,
                contract_snapshot_id=snapshot_id,
                attempt_id=claim.attempt_id,
                attempt_number=claim.attempt_number,
                claim_epoch=claim.claim_epoch,
                cancellation_epoch=claim.cancellation_epoch,
                deadline=datetime.now(UTC) + timedelta(seconds=max(task.timeout_seconds, 1)),
                external_correlation=task.operation_idempotency_key,
                redaction=RedactionPolicy(),
            )
            return _Prepared(
                workflow_id=task.workflow_id,
                phase_run_id=task.phase_run_id,
                task_id=task.task_id,
                capability_id=task.capability_id,
                connector_id=task.connector_id,
                connector_version=task.connector_version,
                operation_key=task.operation_idempotency_key,
                input_digest=task.resolved_input_digest,
                spec=spec,
                connector=connector,
                binding=binding,
                payload=validated,
                context=context,
                intent_id=existing.intent_id,
                policy=decision,
                attempt_count=task.attempt_count,
            )

    async def _persist_success(
        self,
        claim: TaskClaim,
        prepared: _Prepared,
        raw: BaseModel,
        now: datetime,
    ) -> GatewayOutcome:
        try:
            validated = prepared.spec.output_schema.model_validate(
                raw.model_dump(mode="json") if isinstance(raw, BaseModel) else raw
            )
        except ValidationError as exc:
            raise OutputInvalid(str(exc)) from exc
        dumped = validated.model_dump(mode="json")
        async with self._sessions() as session, session.begin():
            adopted = await finalize_success(session, claim=claim, output=dumped, now=now)
            intents = GatewayDispatchRepository(session)
            if not adopted:
                await intents.complete(prepared.intent_id, status="STALE", now=now)
                await append_audit_event(
                    session,
                    workflow_id=prepared.workflow_id,
                    phase_run_id=prepared.phase_run_id,
                    task_id=claim.task_id,
                    attempt_id=claim.attempt_id,
                    operation_idempotency_key=prepared.operation_key,
                    event_type="GATEWAY_STALE_RESULT",
                    payload={"action": "EXECUTE", "intent_id": str(prepared.intent_id)},
                )
                return GatewayOutcome(
                    status="STALE", intent_id=prepared.intent_id, policy=prepared.policy
                )
            evidence = await TwinRepository(session).add_evidence_reference(
                EvidenceReference(
                    evidence_ref_id=uuid4(),
                    evidence_type="gateway_result",
                    media_type="application/json",
                    sha256=_digest(dumped),
                    size_bytes=len(canonical_json_bytes(dumped)),
                    execution_mode=self._execution_mode,
                    source_authority=_authority(prepared.connector_id, prepared.connector_version),
                    producer_operation_key=prepared.operation_key,
                    producer_attempt_id=prepared.context.attempt_id,
                    created_at=now,
                )
            )
            await intents.complete(
                prepared.intent_id,
                status="SUCCEEDED",
                now=now,
                evidence_ref_id=evidence.evidence_ref_id,
                result_digest=_digest(dumped),
            )
            await append_audit_event(
                session,
                workflow_id=prepared.workflow_id,
                phase_run_id=prepared.phase_run_id,
                task_id=claim.task_id,
                attempt_id=claim.attempt_id,
                operation_idempotency_key=prepared.operation_key,
                event_type="GATEWAY_COMPLETED",
                payload={
                    "action": "EXECUTE",
                    "intent_id": str(prepared.intent_id),
                    "evidence_ref_id": str(evidence.evidence_ref_id),
                },
            )
        return GatewayOutcome(
            status="SUCCEEDED",
            output=validated,
            policy=prepared.policy,
            intent_id=prepared.intent_id,
            evidence_ref_id=evidence.evidence_ref_id,
        )

    async def _handle_execute_failure(
        self,
        claim: TaskClaim,
        prepared: _Prepared,
        exc: Exception,
        now: datetime,
        *,
        principal: PrincipalRef,
        authorization: GrantAuthorization,
    ) -> GatewayOutcome:
        failure = _failure_class(exc)
        if prepared.spec.effect_semantics is EffectSemantics.SIDE_EFFECT_FREE:
            return await self._complete_failure(claim, prepared, failure, now)
        recovery: RecoveryClaim | None
        async with self._sessions() as session, session.begin():
            recovery = await acquire_recovery(
                session,
                task_id=claim.task_id,
                recovery_owner=self._owner,
                now=now,
                lease_duration=RECOVERY_LEASE,
                reconcile_deadline=now + RECONCILE_DEADLINE,
                expected_owner=claim.owner,
                expected_epoch=claim.claim_epoch,
                expected_attempt_id=claim.attempt_id,
                expected_cancellation_epoch=claim.cancellation_epoch,
            )
        if recovery is None:
            return await self._complete_failure(claim, prepared, failure, now)
        return await self.reconcile(
            recovery, principal=principal, authorization=authorization, now=now
        )

    async def _complete_failure(
        self,
        claim: TaskClaim,
        prepared: _Prepared,
        failure: str,
        now: datetime,
    ) -> GatewayOutcome:
        async with self._sessions() as session, session.begin():
            await finalize_failure(session, claim=claim, failure_classification=failure, now=now)
            await GatewayDispatchRepository(session).complete(
                prepared.intent_id, status="FAILED", now=now
            )
            await append_audit_event(
                session,
                workflow_id=prepared.workflow_id,
                phase_run_id=prepared.phase_run_id,
                task_id=claim.task_id,
                attempt_id=claim.attempt_id,
                operation_idempotency_key=prepared.operation_key,
                event_type="GATEWAY_FAILED",
                payload={
                    "failure": failure,
                    "intent_id": str(prepared.intent_id),
                },
            )
        return GatewayOutcome(
            status="FAILED",
            policy=prepared.policy,
            intent_id=prepared.intent_id,
            failure_classification=failure,
        )

    async def _complete_action(
        self,
        claim: TaskClaim,
        prepared: _Prepared,
        action: GatewayAction,
        now: datetime,
    ) -> GatewayOutcome:
        async with self._sessions() as session, session.begin():
            await GatewayDispatchRepository(session).complete(
                prepared.intent_id,
                status="SUCCEEDED",
                now=now,
                result_digest=_digest({"action": action}),
            )
            await append_audit_event(
                session,
                workflow_id=prepared.workflow_id,
                phase_run_id=prepared.phase_run_id,
                task_id=claim.task_id,
                attempt_id=claim.attempt_id,
                operation_idempotency_key=prepared.operation_key,
                event_type="GATEWAY_COMPLETED",
                payload={"action": action, "intent_id": str(prepared.intent_id)},
            )
        return GatewayOutcome(
            status="SUCCEEDED", policy=prepared.policy, intent_id=prepared.intent_id
        )

    async def _apply_reconcile(
        self,
        claim: RecoveryClaim,
        spec: CapabilitySpec,
        result: Any,
        intent_id: UUID,
        now: datetime,
        copies: tuple[UUID, UUID, str, str | None, str | None],
    ) -> GatewayOutcome:
        workflow_id, phase_run_id, operation_key, connector_id, connector_version = copies

        def _validate(output: dict[str, Any]) -> dict[str, Any]:
            validated = spec.output_schema.model_validate(output)
            return validated.model_dump(mode="json")

        async with self._sessions() as session, session.begin():
            state = await apply_reconcile_result(
                session,
                claim=claim,
                result=result,
                now=now,
                max_reconcile_checks=MAX_RECONCILE_CHECKS,
                recovery_lease_duration=RECOVERY_LEASE,
                output_validator=_validate if isinstance(result, EffectFound) else None,
            )
            evidence_id: UUID | None = None
            output: BaseModel | None = None
            if isinstance(result, EffectFound) and state is TaskState.SUCCEEDED:
                output = spec.output_schema.model_validate(result.output)
                dumped = output.model_dump(mode="json")
                evidence = await TwinRepository(session).add_evidence_reference(
                    EvidenceReference(
                        evidence_ref_id=uuid4(),
                        evidence_type="gateway_reconcile",
                        media_type="application/json",
                        sha256=_digest(dumped),
                        size_bytes=len(canonical_json_bytes(dumped)),
                        execution_mode=self._execution_mode,
                        source_authority=_authority(connector_id, connector_version),
                        producer_operation_key=operation_key,
                        producer_attempt_id=claim.attempt_id,
                        created_at=now,
                    )
                )
                evidence_id = evidence.evidence_ref_id
            complete_status = "SUCCEEDED" if state is TaskState.SUCCEEDED else state.value
            await GatewayDispatchRepository(session).complete(
                intent_id,
                status=complete_status[:32],
                now=now,
                evidence_ref_id=evidence_id,
                result_digest=_digest(result.model_dump(mode="json")),
            )
            await append_audit_event(
                session,
                workflow_id=workflow_id,
                phase_run_id=phase_run_id,
                task_id=claim.task_id,
                attempt_id=claim.attempt_id,
                operation_idempotency_key=operation_key,
                event_type="GATEWAY_RECONCILED",
                payload={
                    "intent_id": str(intent_id),
                    "result_kind": result.kind,
                    "task_state": state.value,
                },
            )
        status: GatewayStatus = "RECOVERING"
        if state is TaskState.SUCCEEDED:
            status = "SUCCEEDED"
        elif state is TaskState.RETRY_WAIT:
            status = "RETRY_WAIT"
        elif state is TaskState.FAILED:
            status = "FAILED"
        elif state is TaskState.PARKED:
            status = "PARKED"
        return GatewayOutcome(
            status=status,
            output=output,
            intent_id=intent_id,
            evidence_ref_id=evidence_id,
            task_state=state.value,
            recovered=isinstance(result, EffectFound),
        )


def _recovery_context(
    task: MaterializedTaskModel,
    claim: RecoveryClaim,
    spec: CapabilitySpec,
    connector: ConnectorSpec | None,
    now: datetime,
) -> RecoveryContext:
    return RecoveryContext(
        workflow_id=task.workflow_id,
        phase_run_id=task.phase_run_id,
        task_id=task.task_id,
        operation_idempotency_key=task.operation_idempotency_key,
        resolved_input_digest=task.resolved_input_digest,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id=spec.id,
            capability_contract_version=spec.version,
            input_schema_version=spec.input_schema_version,
            output_schema_version=spec.output_schema_version,
        ),
        connector_id=task.connector_id or "unbound",
        connector_version=task.connector_version or (connector.version if connector else "unbound"),
        target_environment=(
            connector.target_environment if connector is not None else TargetEnv.DEV
        ),
        attempts=(
            AttemptRecoveryRef(
                attempt_id=claim.attempt_id, attempt_number=max(task.attempt_count, 1)
            ),
        ),
        reconcile_deadline=now + RECONCILE_DEADLINE,
    )


def _risk_decision(spec: CapabilitySpec) -> dict[str, Any]:
    return {
        "risk": spec.risk.value,
        "effect_semantics": spec.effect_semantics.value,
        "approval": spec.approval.value,
    }


def _authority(connector_id: str | None, connector_version: str | None) -> SourceAuthorityRef:
    return SourceAuthorityRef(
        authority_id=connector_id or "local",
        contract_version=connector_version or "1.0.0",
        scope=("DEVELOPMENT",),
    )


def _failure_class(exc: Exception) -> str:
    failure = getattr(exc, "failure", None)
    if isinstance(failure, FailureClass):
        return failure.value
    mapped = getattr(exc, "failure_class", None)
    if isinstance(mapped, FailureClass):
        return mapped.value
    return FailureClass.CONNECTOR_FAILURE.value


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value
