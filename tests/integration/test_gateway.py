from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.integration.helpers import SeedInput, seed_task

from aide.app.gateway import GovernedToolGateway, gateway_holds_write_transaction
from aide.auth.grants import GrantAuthorizer
from aide.capabilities.registry import CapabilityRegistry
from aide.capabilities.spec import CapabilitySpec, ConnectorRequirement, RetryPolicy
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, NoEffect
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import (
    CapabilityImplementation,
    ConnectorKind,
    ConnectorSpec,
    IdentityClass,
    ObjectAllowList,
)
from aide.domain.approvals import ApprovalRecord, ApprovalStatus, OperationApproval
from aide.domain.effects import EffectSemantics
from aide.domain.enums import ApprovalRule, RiskLevel, TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.identity import compute_resolved_input_digest
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.states import TaskState, WorkflowState
from aide.orchestration.worker import TaskClaim, claim_task
from aide.persistence.models import (
    ApprovalModel,
    AuditEventModel,
    EvidenceReferenceModel,
    GatewayDispatchIntentModel,
    MaterializedTaskModel,
    RecoveryEventModel,
    WorkflowModel,
)
from aide.persistence.repositories import ApprovalRepository
from aide.policy.engine import PolicyEngine


class SpyOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    applied: bool
    value: str


class SpyBinding:
    spec: ConnectorSpec | None

    def __init__(self, sessions: async_sessionmaker[AsyncSession], spec: ConnectorSpec) -> None:
        self._sessions = sessions
        self.spec = spec
        self.execute_calls = 0
        self.reconcile_calls = 0
        self.cancel_calls = 0
        self.intents_before_execute: list[str] = []
        self.crash_after_effect = False
        self.stale_claim = False
        self.effects: dict[str, dict[str, Any]] = {}
        self.health_calls = 0
        self.health_during_write_txn = False

    async def health(self) -> ConnectorHealthSnapshot:
        self.health_calls += 1
        self.health_during_write_txn = gateway_holds_write_transaction()
        now = _naive_now()
        return ConnectorHealthSnapshot(
            connector_id="fake",
            status="MOCK",
            checked_at=now,
            expires_at=now + timedelta(minutes=5),
        )

    async def execute(
        self, capability_id: str, payload: BaseModel, context: CallContext
    ) -> BaseModel:
        del capability_id
        self.execute_calls += 1
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(GatewayDispatchIntentModel).where(
                        GatewayDispatchIntentModel.attempt_id == context.attempt_id,
                        GatewayDispatchIntentModel.action == "EXECUTE",
                    )
                )
            ).all()
            assert rows, "persisted dispatch intent must exist before connector execute"
            self.intents_before_execute.append(rows[0].status)
        if self.stale_claim:
            async with self._sessions() as session, session.begin():
                task = await session.get(MaterializedTaskModel, context.task_id)
                assert task is not None
                task.claim_epoch += 1
        assert isinstance(payload, SeedInput)
        output = SpyOutput(applied=True, value=payload.value)
        self.effects[context.operation_idempotency_key] = output.model_dump(mode="json")
        if self.crash_after_effect:
            raise RuntimeError("crash after effect")
        return output

    async def cancel(self, capability_id: str, context: CallContext) -> None:
        del capability_id, context
        self.cancel_calls += 1

    async def reconcile(self, recovery: RecoveryContext) -> EffectFound | NoEffect:
        self.reconcile_calls += 1
        stored = self.effects.get(recovery.operation_idempotency_key)
        if stored is None:
            return NoEffect(evidence="spy has no matching effect")
        return EffectFound(output=stored, external_ref="spy")


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _capability(
    *,
    capability_id: str = "fake_side_effect",
    approval: ApprovalRule = ApprovalRule.NEVER,
) -> CapabilitySpec:
    return CapabilitySpec(
        id=capability_id,
        version=1,
        kind="deterministic",
        purpose="spy connector for governed gateway tests",
        input_schema=SeedInput,
        output_schema=SpyOutput,
        input_schema_version=1,
        output_schema_version=1,
        required_permission=PermissionLevel.DEVELOPMENT_WRITE,
        risk=RiskLevel.MEDIUM,
        approval=approval,
        timeout_seconds=30,
        retry=RetryPolicy(
            max_attempts=2,
            backoff="none",
            retry_on=frozenset({FailureClass.CONNECTOR_FAILURE}),
        ),
        failure_classes=frozenset({FailureClass.CONNECTOR_FAILURE}),
        connector_requirement=ConnectorRequirement(
            mode="REQUIRED", kinds=frozenset({"transformation"})
        ),
        effect_semantics=EffectSemantics.EXTERNALLY_DEDUPLICATED,
        cost_class="external_api",
    )


def _connector(*capability_ids: str) -> ConnectorSpec:
    ids = capability_ids or ("fake_side_effect",)
    return ConnectorSpec(
        connector_id="fake",
        kind=ConnectorKind.TRANSFORMATION,
        vendor="fake",
        version="1.0",
        target_environment=TargetEnv.DEV,
        identity_class=IdentityClass.DEVELOPMENT,
        implementations=frozenset(
            {
                CapabilityImplementation(
                    capability_id=item,
                    supported_contract_versions=frozenset({1}),
                    input_schema_versions=frozenset({1}),
                    output_schema_versions=frozenset({1}),
                )
                for item in ids
            }
        ),
        allowed_permissions=frozenset({PermissionLevel.DEVELOPMENT_WRITE}),
        allow_list=ObjectAllowList(),
        dialect=None,
        is_fake=True,
    )


def _principal() -> tuple[PrincipalRef, GrantAuthorization]:
    principal = PrincipalRef(
        principal_id=uuid4(),
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=uuid4(),
    )
    authorization = GrantAuthorizer().authorize(
        principal,
        frozenset({PermissionLevel.DEVELOPMENT_WRITE}),
        target_environment=TargetEnv.DEV,
        decided_at=_naive_now(),
    )
    return principal, authorization


def _gateway(
    session_factory: async_sessionmaker[AsyncSession],
    spy: SpyBinding,
    *,
    capability: CapabilitySpec | None = None,
) -> GovernedToolGateway:
    spec = capability or _capability()
    capabilities = CapabilityRegistry()
    capabilities.register(spec)
    connectors = ConnectorRegistry()
    connector = _connector(spec.id)
    connectors.register(connector, capabilities.required_permissions())
    spy.spec = connector
    gateway = GovernedToolGateway(
        session_factory,
        capabilities=capabilities,
        connectors=connectors,
        policy=PolicyEngine(),
    )
    gateway.register_binding(spec.id, spy, connector_id="fake")
    return gateway


@pytest.mark.asyncio
async def test_execute_persists_dispatch_intent_before_connector_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    spy = SpyBinding(session_factory, _connector())
    gateway = _gateway(session_factory, spy)
    principal, authorization = _principal()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=_naive_now(), lease_duration=timedelta(seconds=30)
        )
        assert claim is not None
        assert claim.task_id == seeded.task_id
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert outcome.status == "SUCCEEDED"
    assert outcome.intent_id is not None
    assert outcome.evidence_ref_id is not None
    assert spy.execute_calls == 1
    assert spy.intents_before_execute == ["DISPATCHED"]
    assert spy.health_calls >= 1
    assert spy.health_during_write_txn is False
    async with session_factory() as session:
        intent = await session.get(GatewayDispatchIntentModel, outcome.intent_id)
        assert intent is not None
        assert intent.status == "SUCCEEDED"
        assert intent.action == "EXECUTE"
        assert intent.evidence_ref_id == outcome.evidence_ref_id


@pytest.mark.asyncio
async def test_cancel_records_dispatch_intent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_task(session_factory)
    spy = SpyBinding(session_factory, _connector())
    gateway = _gateway(session_factory, spy)
    principal, authorization = _principal()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=_naive_now(), lease_duration=timedelta(seconds=30)
        )
        assert claim is not None
    cancelled = await gateway.cancel(claim, principal=principal, authorization=authorization)
    assert cancelled.status == "SUCCEEDED"
    assert cancelled.intent_id is not None
    assert spy.cancel_calls == 1
    async with session_factory() as session:
        intent = await session.get(GatewayDispatchIntentModel, cancelled.intent_id)
        assert intent is not None
        assert intent.action == "CANCEL"
        assert intent.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_crash_after_effect_reconciles_before_retry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, max_attempts=2)
    spy = SpyBinding(session_factory, _connector())
    spy.crash_after_effect = True
    gateway = _gateway(session_factory, spy)
    principal, authorization = _principal()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=_naive_now(), lease_duration=timedelta(seconds=30)
        )
        assert claim is not None
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert spy.execute_calls == 1
    assert spy.reconcile_calls == 1
    assert outcome.status == "SUCCEEDED"
    assert outcome.recovered is True
    async with session_factory() as session:
        events = (
            await session.scalars(
                select(RecoveryEventModel).where(RecoveryEventModel.task_id == seeded.task_id)
            )
        ).all()
        assert events
        intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.task_id == seeded.task_id
                )
            )
        ).all()
        actions = {item.action for item in intents}
        assert "EXECUTE" in actions
        assert "RECONCILE" in actions


@pytest.mark.asyncio
async def test_stale_claim_cannot_persist_successful_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory)
    spy = SpyBinding(session_factory, _connector())
    spy.stale_claim = True
    gateway = _gateway(session_factory, spy)
    principal, authorization = _principal()
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=_naive_now(), lease_duration=timedelta(seconds=30)
        )
        assert claim is not None
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert outcome.status == "STALE"
    assert outcome.evidence_ref_id is None
    async with session_factory() as session:
        evidence = (await session.scalars(select(EvidenceReferenceModel))).all()
        assert evidence == []
        intent_rows = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.task_id == seeded.task_id
                )
            )
        ).all()
        assert intent_rows
        assert all(item.evidence_ref_id is None for item in intent_rows)
        assert any(item.status == "STALE" for item in intent_rows)


ALWAYS_CAPABILITY = "fake_needs_approval"


def _always_capability() -> CapabilitySpec:
    return _capability(capability_id=ALWAYS_CAPABILITY, approval=ApprovalRule.ALWAYS)


async def _claim_ready_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> TaskClaim:
    async with session_factory() as session, session.begin():
        claim = await claim_task(
            session, owner="worker", now=_naive_now(), lease_duration=timedelta(seconds=30)
        )
        assert claim is not None
        return claim


async def _task_operation_subject(
    session_factory: async_sessionmaker[AsyncSession],
    task_id: UUID,
    *,
    capability_id: str,
    expires_at: datetime,
    resolved_input_digest: str | None = None,
) -> OperationApproval:
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, task_id)
        assert task is not None
        return OperationApproval(
            operation_idempotency_key=task.operation_idempotency_key,
            resolved_input_digest=resolved_input_digest or task.resolved_input_digest,
            artifact_hashes=(),
            capability_id=capability_id,
            capability_contract_version=1,
            connector_id="fake",
            connector_version="1.0",
            target_environment=TargetEnv.DEV,
            required_permission=PermissionLevel.DEVELOPMENT_WRITE,
            external_state_digest=None,
            expires_at=expires_at,
        )


async def _store_approval(
    session_factory: async_sessionmaker[AsyncSession],
    record: ApprovalRecord,
    *,
    task_id: UUID,
) -> None:
    async with session_factory() as session, session.begin():
        await ApprovalRepository(session).add(record, task_id=task_id)


def _approved_record(
    *,
    workflow_id: UUID,
    subject: OperationApproval,
    principal: PrincipalRef,
    now: datetime,
    expires_at: datetime,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=uuid4(),
        workflow_id=workflow_id,
        subject=subject,
        subject_digest=compute_resolved_input_digest(subject),
        requester=principal,
        status=ApprovalStatus.APPROVED,
        created_at=now,
        expires_at=expires_at,
        decided_by=principal,
        decided_at=now,
    )


@pytest.mark.asyncio
async def test_approval_required_does_not_execute_and_persists_requirement(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, capability_id=ALWAYS_CAPABILITY)
    spy = SpyBinding(session_factory, _connector(ALWAYS_CAPABILITY))
    gateway = _gateway(session_factory, spy, capability=_always_capability())
    principal, authorization = _principal()
    claim = await _claim_ready_task(session_factory)
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert outcome.status == "AWAITING_APPROVAL"
    assert outcome.policy is not None
    assert outcome.policy.decision == "REQUIRE_APPROVAL"
    assert spy.execute_calls == 0
    assert spy.health_during_write_txn is False
    async with session_factory() as session:
        task = await session.get(MaterializedTaskModel, seeded.task_id)
        workflow = await session.get(WorkflowModel, seeded.workflow_id)
        assert task is not None and workflow is not None
        assert task.status == TaskState.AWAITING_APPROVAL.value
        assert workflow.state == WorkflowState.APPROVAL_REQUIRED.value
        approvals = (await session.scalars(select(ApprovalModel))).all()
        assert len(approvals) == 1
        assert approvals[0].status == ApprovalStatus.PENDING.value
        assert approvals[0].task_id == seeded.task_id
        assert approvals[0].workflow_id == seeded.workflow_id
        execute_intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.task_id == seeded.task_id,
                    GatewayDispatchIntentModel.action == "EXECUTE",
                )
            )
        ).all()
        assert execute_intents == []
        events = (
            await session.scalars(
                select(AuditEventModel).where(AuditEventModel.event_type == "APPROVAL_REQUIRED")
            )
        ).all()
        assert events


@pytest.mark.asyncio
async def test_matching_approved_record_allows_execution_and_binds_approval_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, capability_id=ALWAYS_CAPABILITY)
    now = _naive_now()
    principal, authorization = _principal()
    subject = await _task_operation_subject(
        session_factory,
        seeded.task_id,
        capability_id=ALWAYS_CAPABILITY,
        expires_at=now + timedelta(hours=1),
    )
    record = _approved_record(
        workflow_id=seeded.workflow_id,
        subject=subject,
        principal=principal,
        now=now,
        expires_at=now + timedelta(hours=1),
    )
    await _store_approval(session_factory, record, task_id=seeded.task_id)
    spy = SpyBinding(session_factory, _connector(ALWAYS_CAPABILITY))
    gateway = _gateway(session_factory, spy, capability=_always_capability())
    claim = await _claim_ready_task(session_factory)
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert outcome.status == "SUCCEEDED"
    assert spy.execute_calls == 1
    assert spy.intents_before_execute == ["DISPATCHED"]
    assert spy.health_during_write_txn is False
    async with session_factory() as session:
        intent = await session.get(GatewayDispatchIntentModel, outcome.intent_id)
        assert intent is not None
        assert intent.approval_id == record.approval_id
        assert intent.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_expired_approval_does_not_allow_execution(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, capability_id=ALWAYS_CAPABILITY)
    now = _naive_now()
    principal, authorization = _principal()
    expired_at = now - timedelta(minutes=1)
    subject = await _task_operation_subject(
        session_factory,
        seeded.task_id,
        capability_id=ALWAYS_CAPABILITY,
        expires_at=expired_at,
    )
    record = _approved_record(
        workflow_id=seeded.workflow_id,
        subject=subject,
        principal=principal,
        now=now - timedelta(hours=1),
        expires_at=expired_at,
    )
    await _store_approval(session_factory, record, task_id=seeded.task_id)
    spy = SpyBinding(session_factory, _connector(ALWAYS_CAPABILITY))
    gateway = _gateway(session_factory, spy, capability=_always_capability())
    claim = await _claim_ready_task(session_factory)
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert outcome.status == "AWAITING_APPROVAL"
    assert spy.execute_calls == 0
    async with session_factory() as session:
        pending = (
            await session.scalars(
                select(ApprovalModel).where(ApprovalModel.status == ApprovalStatus.PENDING.value)
            )
        ).all()
        assert pending
        execute_intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.action == "EXECUTE"
                )
            )
        ).all()
        assert execute_intents == []


@pytest.mark.asyncio
async def test_mismatched_approval_does_not_allow_execution(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seeded = await seed_task(session_factory, capability_id=ALWAYS_CAPABILITY)
    now = _naive_now()
    principal, authorization = _principal()
    subject = await _task_operation_subject(
        session_factory,
        seeded.task_id,
        capability_id=ALWAYS_CAPABILITY,
        expires_at=now + timedelta(hours=1),
        resolved_input_digest="c" * 64,
    )
    record = _approved_record(
        workflow_id=seeded.workflow_id,
        subject=subject,
        principal=principal,
        now=now,
        expires_at=now + timedelta(hours=1),
    )
    await _store_approval(session_factory, record, task_id=seeded.task_id)
    spy = SpyBinding(session_factory, _connector(ALWAYS_CAPABILITY))
    gateway = _gateway(session_factory, spy, capability=_always_capability())
    claim = await _claim_ready_task(session_factory)
    outcome = await gateway.execute(claim, principal=principal, authorization=authorization)
    assert outcome.status == "AWAITING_APPROVAL"
    assert spy.execute_calls == 0
    async with session_factory() as session:
        pending = (
            await session.scalars(
                select(ApprovalModel).where(ApprovalModel.status == ApprovalStatus.PENDING.value)
            )
        ).all()
        assert pending
        execute_intents = (
            await session.scalars(
                select(GatewayDispatchIntentModel).where(
                    GatewayDispatchIntentModel.action == "EXECUTE"
                )
            )
        ).all()
        assert execute_intents == []
