"""Repository boundaries for durable contract records."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.domain.approvals import ApprovalRecord, ApprovalStatus, ApprovalSubject
from aide.domain.artifacts import ArtifactProvenance
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role
from aide.domain.states import WorkflowState
from aide.domain.versions import ContractSnapshot
from aide.persistence.models import (
    ApprovalModel,
    ArtifactModel,
    ConnectorHealthModel,
    ContractSnapshotModel,
    MaterializedTaskModel,
    PhaseRunModel,
    SessionModel,
    TaskAttemptModel,
    TaskTemplateModel,
    UnresolvedEffectModel,
    WorkflowGrantModel,
    WorkflowModel,
)

_APPROVAL_SUBJECT_ADAPTER: TypeAdapter[ApprovalSubject] = TypeAdapter(ApprovalSubject)


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, state: WorkflowState = WorkflowState.RECEIVED) -> WorkflowModel:
        workflow = WorkflowModel(state=state.value)
        self._session.add(workflow)
        await self._session.flush()
        return workflow

    async def get(self, workflow_id: UUID, *, for_update: bool = False) -> WorkflowModel:
        statement = select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id)
        if for_update:
            statement = statement.with_for_update()
        workflow = await self._session.scalar(statement)
        if workflow is None:
            raise LookupError(f"workflow {workflow_id} does not exist")
        return workflow


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        principal: PrincipalRef,
        opaque_token_digest: str,
        csrf_token_digest: str,
        expires_at: datetime,
    ) -> SessionModel:
        row = SessionModel(
            session_id=principal.session_id,
            principal_id=principal.principal_id,
            authentication_source=principal.authentication_source,
            roles=sorted(role.value for role in principal.roles),
            opaque_token_digest=opaque_token_digest,
            csrf_token_digest=csrf_token_digest,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_active(self, session_id: UUID, *, at: datetime) -> SessionModel | None:
        row: SessionModel | None = await self._session.scalar(
            select(SessionModel).where(
                SessionModel.session_id == session_id,
                SessionModel.expires_at > at,
                SessionModel.revoked_at.is_(None),
            )
        )
        return row

    async def get_by_token_digest(self, opaque_token_digest: str) -> SessionModel | None:
        row: SessionModel | None = await self._session.scalar(
            select(SessionModel).where(SessionModel.opaque_token_digest == opaque_token_digest)
        )
        return row


class GrantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist(
        self, *, workflow_id: UUID, authorization: GrantAuthorization
    ) -> tuple[WorkflowGrantModel, ...]:
        rows = tuple(
            WorkflowGrantModel(
                workflow_id=workflow_id,
                principal_id=authorization.principal.principal_id,
                permission=permission.value,
                environment_policy_version=authorization.environment_policy_version,
                decided_at=authorization.decided_at,
            )
            for permission in sorted(authorization.effective, key=PermissionLevel.__str__)
        )
        self._session.add_all(rows)
        await self._session.flush()
        return rows


class ContractSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, workflow_id: UUID, snapshot: ContractSnapshot) -> ContractSnapshotModel:
        row = ContractSnapshotModel(
            snapshot_id=snapshot.snapshot_id,
            workflow_id=workflow_id,
            capability_contracts=[
                item.model_dump(mode="json") for item in snapshot.capability_contracts
            ],
            connector_versions=snapshot.connector_versions,
        )
        self._session.add(row)
        await self._session.flush()
        return row


class PhaseRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, phase_run_id: UUID, *, for_update: bool = False) -> PhaseRunModel:
        statement = select(PhaseRunModel).where(PhaseRunModel.phase_run_id == phase_run_id)
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise LookupError(f"phase occurrence {phase_run_id} does not exist")
        return row

    async def templates(self, phase_run_id: UUID) -> tuple[TaskTemplateModel, ...]:
        rows = await self._session.scalars(
            select(TaskTemplateModel)
            .where(TaskTemplateModel.phase_run_id == phase_run_id)
            .order_by(TaskTemplateModel.local_id)
        )
        return tuple(rows.all())


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, task_id: UUID, *, for_update: bool = False) -> MaterializedTaskModel:
        statement = select(MaterializedTaskModel).where(MaterializedTaskModel.task_id == task_id)
        if for_update:
            statement = statement.with_for_update()
        row = await self._session.scalar(statement)
        if row is None:
            raise LookupError(f"task {task_id} does not exist")
        return row

    async def attempts(self, task_id: UUID) -> tuple[TaskAttemptModel, ...]:
        rows = await self._session.scalars(
            select(TaskAttemptModel)
            .where(TaskAttemptModel.task_id == task_id)
            .order_by(TaskAttemptModel.attempt_number)
        )
        return tuple(rows.all())


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        record: ApprovalRecord,
        *,
        task_id: UUID | None,
        mandatory: bool = True,
    ) -> ApprovalModel:
        row = ApprovalModel(
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            task_id=task_id,
            subject=record.subject.model_dump(mode="json"),
            subject_digest=record.subject_digest,
            requester_principal_id=record.requester.principal_id,
            status=record.status.value,
            mandatory=mandatory,
            created_at=record.created_at,
            expires_at=record.expires_at,
            decided_by_principal_id=(
                record.decided_by.principal_id if record.decided_by is not None else None
            ),
            decided_at=record.decided_at,
            comment=record.comment,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_workflow(self, workflow_id: UUID) -> tuple[ApprovalRecord, ...]:
        rows = (
            await self._session.scalars(
                select(ApprovalModel)
                .where(ApprovalModel.workflow_id == workflow_id)
                .order_by(ApprovalModel.created_at, ApprovalModel.approval_id)
            )
        ).all()
        return await self._records_from_rows(rows)

    async def list_for_task(self, task_id: UUID) -> tuple[ApprovalRecord, ...]:
        rows = (
            await self._session.scalars(
                select(ApprovalModel)
                .where(ApprovalModel.task_id == task_id)
                .order_by(ApprovalModel.created_at, ApprovalModel.approval_id)
            )
        ).all()
        return await self._records_from_rows(rows)

    async def _records_from_rows(self, rows: Sequence[ApprovalModel]) -> tuple[ApprovalRecord, ...]:
        if not rows:
            return ()
        principal_ids = {row.requester_principal_id for row in rows}
        principal_ids.update(
            row.decided_by_principal_id for row in rows if row.decided_by_principal_id is not None
        )
        sessions = (
            await self._session.scalars(
                select(SessionModel).where(SessionModel.principal_id.in_(principal_ids))
            )
        ).all()
        by_principal = {item.principal_id: item for item in sessions}
        return tuple(_approval_record_from_model(row, by_principal) for row in rows)


def _approval_record_from_model(
    row: ApprovalModel, sessions: dict[UUID, SessionModel]
) -> ApprovalRecord:
    subject = _naive_approval_subject(_APPROVAL_SUBJECT_ADAPTER.validate_python(row.subject))
    return ApprovalRecord(
        approval_id=row.approval_id,
        workflow_id=row.workflow_id,
        subject=subject,
        subject_digest=row.subject_digest,
        requester=_principal_ref(row.requester_principal_id, sessions),
        status=ApprovalStatus(row.status),
        created_at=_naive_utc(row.created_at),
        expires_at=_naive_utc(row.expires_at),
        decided_by=(
            _principal_ref(row.decided_by_principal_id, sessions)
            if row.decided_by_principal_id is not None
            else None
        ),
        decided_at=_naive_utc(row.decided_at) if row.decided_at is not None else None,
        comment=row.comment,
    )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _naive_approval_subject(subject: ApprovalSubject) -> ApprovalSubject:
    expires = subject.expires_at
    if expires.tzinfo is None:
        return subject
    return subject.model_copy(update={"expires_at": _naive_utc(expires)})


def _principal_ref(principal_id: UUID, sessions: dict[UUID, SessionModel]) -> PrincipalRef:
    row = sessions.get(principal_id)
    if row is None:
        return PrincipalRef(
            principal_id=principal_id,
            authentication_source="LOCAL_SESSION",
            roles=frozenset(),
            session_id=principal_id,
        )
    return PrincipalRef(
        principal_id=row.principal_id,
        authentication_source="LOCAL_SESSION",
        roles=frozenset(Role(item) for item in row.roles),
        session_id=row.session_id,
    )


class ArtifactRepository:
    """PostgreSQL implementation of the V1 immutable artifact/blob boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        workflow_id: UUID,
        task_id: UUID | None,
        artifact_type: str,
        version: int,
        schema_version: int,
        sha256: str,
        provenance: ArtifactProvenance,
        body: dict[str, Any] | None = None,
        blob: bytes | None = None,
    ) -> ArtifactModel:
        if (body is None) == (blob is None):
            raise ValueError("exactly one of body or blob must be provided")
        row = ArtifactModel(
            workflow_id=workflow_id,
            task_id=task_id,
            artifact_type=artifact_type,
            version=version,
            schema_version=schema_version,
            sha256=sha256,
            provenance=provenance.model_dump(mode="json"),
            body=body,
            blob=blob,
        )
        self._session.add(row)
        await self._session.flush()
        return row


class ConnectorHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, snapshot: ConnectorHealthSnapshot) -> ConnectorHealthModel:
        row = ConnectorHealthModel(
            connector_id=snapshot.connector_id,
            status=snapshot.status,
            checked_at=snapshot.checked_at,
            expires_at=snapshot.expires_at,
            missing_permissions=sorted(item.value for item in snapshot.missing_permissions),
            reason_codes=list(snapshot.reason_codes),
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def latest(self, connector_id: str) -> ConnectorHealthModel | None:
        row: ConnectorHealthModel | None = await self._session.scalar(
            select(ConnectorHealthModel)
            .where(ConnectorHealthModel.connector_id == connector_id)
            .order_by(ConnectorHealthModel.checked_at.desc())
            .limit(1)
        )
        return row


class RecoveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def unresolved_for_workflow(self, workflow_id: UUID) -> tuple[UnresolvedEffectModel, ...]:
        rows = await self._session.scalars(
            select(UnresolvedEffectModel)
            .where(UnresolvedEffectModel.workflow_id == workflow_id)
            .order_by(UnresolvedEffectModel.created_at)
        )
        return tuple(rows.all())
