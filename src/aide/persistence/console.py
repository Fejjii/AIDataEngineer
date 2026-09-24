"""Persistence for the operator console run history."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from aide.persistence.models import (
    ArtifactModel,
    AuditEventModel,
    OperatorConsoleRunModel,
    WorkflowModel,
    utcnow,
)

SNAPSHOT_ARTIFACT_TYPE = "operator_console_snapshot"
# Only these persisted artifact types are read back for the console. Every entry is
# already written by the Supervisor or the console itself; nothing here is derived.
EVIDENCE_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {
        SNAPSHOT_ARTIFACT_TYPE,
        "quality_results",
        "verifier_verdict",
        "repair_proposal",
        "repair_validation",
        "repair_application",
        "original_failure",
        "schema_drift",
        "dbt_parse",
        "dbt_compile",
        "dbt_execution",
        "dbt_tests",
        "post_repair_validation",
        "reconciliation",
        "revenue_payment_reconciliation",
        "evidence_bundle",
    }
)


class ConsoleRunRepository:
    """Read and write operator console runs. Callers own the transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, run_id: UUID, principal_id: UUID, started_at: datetime) -> None:
        self._session.add(
            OperatorConsoleRunModel(
                run_id=run_id,
                status="running",
                principal_id=principal_id,
                workflow_ids=[],
                started_at=started_at,
            )
        )
        await self._session.flush()

    async def get(self, run_id: UUID) -> OperatorConsoleRunModel | None:
        return await self._session.get(OperatorConsoleRunModel, run_id)

    async def list_recent(self, *, limit: int = 20) -> tuple[OperatorConsoleRunModel, ...]:
        rows = (
            await self._session.scalars(
                select(OperatorConsoleRunModel)
                .order_by(OperatorConsoleRunModel.created_at.desc(), OperatorConsoleRunModel.run_id)
                .limit(limit)
            )
        ).all()
        return tuple(rows)

    async def complete(
        self,
        run_id: UUID,
        *,
        workflow_ids: list[str],
        snapshot_artifact_id: UUID | None,
        finished_at: datetime,
    ) -> None:
        row = await self.get(run_id)
        if row is None or row.status != "running":
            return
        row.status = "completed"
        row.workflow_ids = workflow_ids
        row.snapshot_artifact_id = snapshot_artifact_id
        row.finished_at = finished_at
        row.error_message = None

    async def fail(
        self,
        run_id: UUID,
        *,
        message: str,
        finished_at: datetime,
        workflow_ids: list[str] | None = None,
    ) -> None:
        row = await self.get(run_id)
        if row is None or row.status != "running":
            return
        row.status = "failed"
        row.error_message = message
        row.finished_at = finished_at
        if workflow_ids:
            row.workflow_ids = workflow_ids

    async def fail_interrupted(self, *, message: str, finished_at: datetime) -> None:
        await self._session.execute(
            update(OperatorConsoleRunModel)
            .where(OperatorConsoleRunModel.status == "running")
            .values(status="failed", error_message=message, finished_at=finished_at)
        )

    async def workflow_states(self, workflow_ids: tuple[UUID, ...]) -> dict[UUID, str]:
        if not workflow_ids:
            return {}
        rows = (
            await self._session.scalars(
                select(WorkflowModel).where(WorkflowModel.workflow_id.in_(workflow_ids))
            )
        ).all()
        return {row.workflow_id: row.state for row in rows}

    async def allowlisted_artifacts(
        self, workflow_ids: tuple[UUID, ...]
    ) -> dict[UUID, dict[str, dict[str, Any]]]:
        """Latest body of each allowlisted artifact type. Other types are ignored."""
        if not workflow_ids:
            return {}
        rows = (
            await self._session.scalars(
                select(ArtifactModel)
                .where(
                    ArtifactModel.workflow_id.in_(workflow_ids),
                    ArtifactModel.artifact_type.in_(tuple(EVIDENCE_ARTIFACT_TYPES)),
                )
                .order_by(ArtifactModel.version, ArtifactModel.created_at)
            )
        ).all()
        found: dict[UUID, dict[str, dict[str, Any]]] = {}
        for row in rows:
            if not isinstance(row.body, dict):
                continue
            found.setdefault(row.workflow_id, {})[row.artifact_type] = row.body
        return found

    async def snapshot_bodies(
        self, artifact_ids: tuple[UUID, ...]
    ) -> dict[UUID, dict[str, Any]]:
        """Console snapshot bodies keyed by artifact id. Used for the history list."""
        if not artifact_ids:
            return {}
        rows = (
            await self._session.scalars(
                select(ArtifactModel).where(
                    ArtifactModel.artifact_id.in_(artifact_ids),
                    ArtifactModel.artifact_type == SNAPSHOT_ARTIFACT_TYPE,
                )
            )
        ).all()
        return {row.artifact_id: row.body for row in rows if isinstance(row.body, dict)}

    async def audit_events(
        self, workflow_ids: tuple[UUID, ...], *, limit: int = 80
    ) -> tuple[AuditEventModel, ...]:
        if not workflow_ids:
            return ()
        rows = (
            await self._session.scalars(
                select(AuditEventModel)
                .where(AuditEventModel.workflow_id.in_(workflow_ids))
                .order_by(AuditEventModel.workflow_id, AuditEventModel.sequence)
                .limit(limit)
            )
        ).all()
        return tuple(rows)


def console_now() -> datetime:
    return utcnow()
