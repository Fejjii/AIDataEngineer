"""Authenticated operator runs of the fixed synthetic scenario."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.errors import DemoBusyError
from aide.app.benchmarking.service import SyntheticInterviewDemoService
from aide.app.console.present import (
    AuditEventView,
    Dashboard,
    ExportFile,
    RunPage,
    RunSummary,
    build_dashboard,
    export_file,
    present_run,
    summarize_snapshot,
)
from aide.app.console.snapshot import (
    SNAPSHOT_SCHEMA_VERSION,
    build_operator_snapshot,
    public_failure_message,
)
from aide.app.console.sources import SourceCatalogView, group_source_catalog, load_source_catalog
from aide.app.sessions import LocalSessionService
from aide.app.supervisor import InterviewResult
from aide.auth.session import IssuedLocalSession
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.benchmark import BenchmarkResult
from aide.domain.identity import canonical_json_bytes
from aide.domain.principal import Role
from aide.persistence.console import SNAPSHOT_ARTIFACT_TYPE, ConsoleRunRepository, console_now
from aide.persistence.repositories import ArtifactRepository

_MIN_PASSWORD_LENGTH = 12
EXPORT_NAMES = frozenset(
    {
        "output-preview",
        "original-sql",
        "repaired-sql",
        "generated-sql",
        "quality",
        "verifier",
        "tests",
    }
)
_INTERRUPTED = "The process restarted before this run finished. Completion evidence is unavailable."


class OperatorConsoleService:
    """Persist scenario runs and read allowlisted evidence back for the console."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        sessions: LocalSessionService,
        demo: SyntheticInterviewDemoService,
        operator_password: str | None,
    ) -> None:
        self._factory = session_factory
        self._sessions = sessions
        self._demo = demo
        self._password = (operator_password or "").strip()
        self._tasks: set[asyncio.Task[None]] = set()

    def password_configured(self) -> bool:
        return len(self._password) >= _MIN_PASSWORD_LENGTH

    def password_matches(self, provided: str) -> bool:
        if not self.password_configured():
            return False
        expected = hashlib.sha256(self._password.encode()).digest()
        actual = hashlib.sha256(provided.encode()).digest()
        return hmac.compare_digest(expected, actual)

    async def issue_operator_session(self) -> IssuedLocalSession:
        return await self._sessions.issue(roles=frozenset({Role.OPERATOR}))

    def source_catalog(self) -> SourceCatalogView:
        return group_source_catalog(load_source_catalog())

    async def reconcile_interrupted_runs(self) -> None:
        async with self._factory() as db, db.begin():
            await ConsoleRunRepository(db).fail_interrupted(
                message=_INTERRUPTED,
                finished_at=console_now(),
            )

    async def start_run(self, principal_id: UUID) -> UUID:
        if not self._demo.try_begin():
            raise DemoBusyError("synthetic interview demo is already running")
        run_id = uuid4()
        try:
            async with self._factory() as db, db.begin():
                await ConsoleRunRepository(db).add(
                    run_id=run_id,
                    principal_id=principal_id,
                    started_at=console_now(),
                )
        except Exception:
            self._demo.end()
            raise
        task = asyncio.create_task(self._execute(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

    async def wait(self) -> None:
        pending = tuple(self._tasks)
        if pending:
            await asyncio.gather(*pending)

    async def dashboard(self) -> Dashboard:
        return build_dashboard(await self.list_runs())

    async def list_runs(self) -> tuple[RunSummary, ...]:
        async with self._factory() as db:
            repo = ConsoleRunRepository(db)
            rows = await repo.list_recent()
            snapshot_ids = tuple(
                row.snapshot_artifact_id for row in rows if row.snapshot_artifact_id is not None
            )
            snapshots = await repo.snapshot_bodies(snapshot_ids)
        summaries: list[RunSummary] = []
        for row in rows:
            body = (
                snapshots.get(row.snapshot_artifact_id)
                if row.snapshot_artifact_id is not None
                else None
            )
            verifier, benchmark, models = summarize_snapshot(body)
            summaries.append(
                RunSummary(
                    run_id=str(row.run_id),
                    status=row.status,
                    started_at=_stamp(row.started_at),
                    finished_at=_stamp(row.finished_at) if row.finished_at is not None else "",
                    workflow_count=len(row.workflow_ids or []),
                    verifier_verdict=verifier,
                    benchmark_verdict=benchmark,
                    models_generated=models,
                )
            )
        return tuple(summaries)

    async def run_page(self, run_id: UUID) -> RunPage | None:
        async with self._factory() as db:
            repo = ConsoleRunRepository(db)
            row = await repo.get(run_id)
            if row is None:
                return None
            identifiers = _parse_ids(list(row.workflow_ids or []))
            states = await repo.workflow_states(identifiers)
            artifacts = await repo.allowlisted_artifacts(identifiers)
            events = await repo.audit_events(identifiers)
        return present_run(
            run_id=str(row.run_id),
            status=row.status,
            error_message=row.error_message,
            started_at=_stamp(row.started_at),
            finished_at=_stamp(row.finished_at) if row.finished_at is not None else None,
            workflow_ids=tuple(str(item) for item in identifiers),
            control_plane_states={str(key): value for key, value in states.items()},
            artifacts={str(key): value for key, value in artifacts.items()},
            audit_events=tuple(
                AuditEventView(
                    workflow_id=str(event.workflow_id),
                    sequence=int(event.sequence),
                    event_type=event.event_type,
                    created_at=_stamp(event.created_at),
                )
                for event in events
            ),
        )

    async def export(self, run_id: UUID, name: str) -> ExportFile | None:
        if name not in EXPORT_NAMES:
            return None
        page = await self.run_page(run_id)
        if page is None or page.status != "completed":
            return None
        return export_file(page, name)

    async def _execute(self, run_id: UUID) -> None:
        first: InterviewResult | None = None
        second: InterviewResult | None = None
        try:
            _report, first, second = await self._demo.execute_benchmark()
            await self._store_success(run_id, _report, first, second)
        except Exception as exc:
            identifiers = _workflow_ids(first, second)
            await self._store_failure(run_id, public_failure_message(exc), identifiers)
        finally:
            self._demo.end()

    async def _store_success(
        self,
        run_id: UUID,
        report: BenchmarkResult,
        first: InterviewResult,
        second: InterviewResult,
    ) -> None:
        snapshot = build_operator_snapshot(report, first, second)
        digest = hashlib.sha256(canonical_json_bytes(snapshot)).hexdigest()
        provenance = ArtifactProvenance(
            execution_mode=ExecutionMode.MOCK,
            connector_id=None,
            connector_version=None,
            capability_id="operator_console",
            capability_version=1,
            operation_idempotency_key=digest,
            resolved_input_digest=digest,
        )
        async with self._factory() as db, db.begin():
            artifacts = ArtifactRepository(db)
            version = await artifacts.next_version(first.workflow_id, SNAPSHOT_ARTIFACT_TYPE)
            stored = await artifacts.add(
                workflow_id=first.workflow_id,
                task_id=None,
                artifact_type=SNAPSHOT_ARTIFACT_TYPE,
                version=version,
                schema_version=SNAPSHOT_SCHEMA_VERSION,
                sha256=digest,
                provenance=provenance,
                body=snapshot,
            )
            await ConsoleRunRepository(db).complete(
                run_id,
                workflow_ids=[str(first.workflow_id), str(second.workflow_id)],
                snapshot_artifact_id=stored.artifact_id,
                finished_at=console_now(),
            )

    async def _store_failure(
        self,
        run_id: UUID,
        message: str,
        workflow_ids: list[str],
    ) -> None:
        async with self._factory() as db, db.begin():
            await ConsoleRunRepository(db).fail(
                run_id,
                message=message,
                finished_at=console_now(),
                workflow_ids=workflow_ids,
            )


def _parse_ids(values: list[str]) -> tuple[UUID, ...]:
    parsed: list[UUID] = []
    for item in values:
        try:
            parsed.append(UUID(str(item)))
        except ValueError:
            continue
    return tuple(parsed)


def _workflow_ids(first: InterviewResult | None, second: InterviewResult | None) -> list[str]:
    if first is None or second is None:
        return []
    return [str(first.workflow_id), str(second.workflow_id)]


def _stamp(value: object) -> str:
    text = getattr(value, "isoformat", None)
    if callable(text):
        rendered = text(sep=" ", timespec="seconds")
        if isinstance(rendered, str):
            return rendered + " UTC"
    return ""
