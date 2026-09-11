"""Repository boundaries for durable contract records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef
from aide.domain.states import WorkflowState
from aide.domain.versions import ContractSnapshot
from aide.persistence.models import (
    ContractSnapshotModel,
    SessionModel,
    WorkflowGrantModel,
    WorkflowModel,
)


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
        return await self._session.scalar(
            select(SessionModel).where(
                SessionModel.session_id == session_id,
                SessionModel.expires_at > at,
                SessionModel.revoked_at.is_(None),
            )
        )


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
