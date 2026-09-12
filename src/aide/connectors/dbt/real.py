"""Real dbt connector: isolated dbtRunner subprocess, DuckDB offline target."""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from uuid import UUID, uuid4

from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.dbt.artifacts import (
    ArtifactBundle,
    artifact_ref,
    capture_target_artifacts,
    compiled_sql_from_manifest,
    lineage_from_manifest,
    node_results_from_run_results,
    parse_manifest,
    parse_run_results,
    provenance_for,
    test_results_from_run_results,
)
from aide.connectors.dbt.config import (
    DbtAdapter,
    DbtSettings,
    duckdb_dbt_settings,
    missing_secret_names,
    render_profiles_yaml,
)
from aide.connectors.dbt.contracts import (
    CompiledModel,
    CompileTransformationInput,
    CompileTransformationOutput,
    CreateTransformationInput,
    CreateTransformationOutput,
    ExecuteTransformationInput,
    ExecuteTransformationOutput,
    GetLineageInput,
    GetLineageOutput,
    LineageEdge,
    LineageNode,
    RunPipelineInput,
    RunPipelineOutput,
    RunTestsInput,
    RunTestsOutput,
    TransformationIssue,
)
from aide.connectors.dbt.errors import (
    DbtMappedError,
    DbtProcessTerminatedError,
    DbtTimeoutError,
    map_exception_name,
)
from aide.connectors.dbt.journal import (
    DispatchStatus,
    InvocationJournalEntry,
    append_journal,
    find_latest_journal_for_operation,
    utc_now_iso,
)
from aide.connectors.dbt.reconcile import reconcile_create_transformation, reconcile_invocation
from aide.connectors.dbt.runner import (
    IsolatedResult,
    build_controlled_env,
    remaining_timeout_seconds,
    run_dbt,
)
from aide.connectors.dbt.specs import DBT_DEV
from aide.connectors.dbt.workspace import (
    default_project_template,
    duckdb_workspace_path,
    ensure_project_copy,
    invocation_dir,
    profiles_dir,
    project_dir,
    workflow_root,
    write_project_files,
)
from aide.domain.artifacts import ArtifactProvenance
from aide.domain.effects import EffectSemantics
from aide.domain.failures import FailureClass

HEALTH_TTL = timedelta(minutes=5)


def _distribution_installed(name: str) -> bool:
    try:
        distribution_version(name)
        return True
    except PackageNotFoundError:
        return False


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


class RealDbtConnector:
    """Subprocess dbt Core connector. DuckDB credentials/files only in Cloud."""

    def __init__(self, spec: ConnectorSpec | None, settings: DbtSettings) -> None:
        self.spec = spec or DBT_DEV
        self.settings = settings
        self._states: dict[UUID, Path] = {}
        self._written_hashes: dict[str, dict[str, str]] = {}

    async def health(self) -> ConnectorHealthSnapshot:
        now = datetime.now(UTC).replace(tzinfo=None)
        reasons: list[str] = []
        if not _distribution_installed("dbt-core") and not _module_available("dbt"):
            reasons.append("DBT_CORE_UNAVAILABLE")
        if self.settings.adapter is DbtAdapter.DUCKDB:
            if not _distribution_installed("dbt-duckdb"):
                reasons.append("DBT_ADAPTER_UNAVAILABLE")
        else:
            missing = missing_secret_names(self.settings)
            reasons.extend(f"SECRET_UNRESOLVED:{name}" for name in missing)
            if not _distribution_installed("dbt-snowflake"):
                reasons.append("DBT_ADAPTER_UNAVAILABLE")
        status = "UNAVAILABLE" if reasons else "AVAILABLE"
        return ConnectorHealthSnapshot(
            connector_id=self.spec.connector_id,
            status=status,  # type: ignore[arg-type]
            checked_at=now,
            expires_at=now + HEALTH_TTL,
            reason_codes=tuple(reasons),
        )

    async def close(self) -> None:
        return None

    async def create_transformation(
        self, payload: CreateTransformationInput, context: CallContext
    ) -> CreateTransformationOutput:
        project, _profiles, _duck = self._ensure_workspace(context.workflow_id)
        written = write_project_files(project, payload.files, mode=payload.mode)
        state_id = uuid4()
        self._states[state_id] = project
        hashes = {item.path: item.sha256 for item in written}
        self._written_hashes[context.operation_idempotency_key] = hashes
        self._journal(
            context,
            operation="create_transformation",
            status=DispatchStatus.COMPLETED,
            selected=(),
            hashes=hashes,
            effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
            applied=True,
        )
        return CreateTransformationOutput(written=written, project_state_id=state_id)

    async def compile_transformation(
        self, payload: CompileTransformationInput, context: CallContext
    ) -> CompileTransformationOutput:
        args = ["compile", *self._select_args(payload.select), *self._project_args(context)]
        result, bundle = await self._invoke(
            context,
            args,
            operation="compile_transformation",
            effect=EffectSemantics.SIDE_EFFECT_FREE,
            selected=payload.select or (),
        )
        provenance = self._provenance(context, "compile_transformation")
        if result.exit_code != 0:
            failure = self._classify_result(result)
            return CompileTransformationOutput(
                ok=False,
                errors=(TransformationIssue(message=_safe_message(result), error_class=failure),),
            )
        compiled: list[CompiledModel] = []
        manifest_ref = None
        if bundle.manifest_path is not None:
            manifest = parse_manifest(bundle.manifest_path)
            sql_by_id = compiled_sql_from_manifest(manifest)
            for unique_id, sql in sql_by_id.items():
                compiled.append(CompiledModel(model=unique_id.split(".")[-1], compiled_sql=sql))
            manifest_ref = artifact_ref(
                sha256=bundle.hashes["manifest.json"],
                artifact_type="manifest.json",
                provenance=provenance,
            )
        return CompileTransformationOutput(
            ok=True, manifest_ref=manifest_ref, compiled=tuple(compiled)
        )

    async def execute_transformation(
        self, payload: ExecuteTransformationInput, context: CallContext
    ) -> ExecuteTransformationOutput:
        args = ["run", *self._select_args(payload.select), *self._project_args(context)]
        if payload.full_refresh:
            args.append("--full-refresh")
        result, bundle = await self._invoke(
            context,
            args,
            operation="execute_transformation",
            effect=EffectSemantics.NON_IDEMPOTENT,
            selected=payload.select,
        )
        return self._execute_output(context, result, bundle, "execute_transformation")

    async def run_pipeline(
        self, payload: RunPipelineInput, context: CallContext
    ) -> RunPipelineOutput:
        args = ["build", *self._select_args(payload.select), *self._project_args(context)]
        if payload.full_refresh:
            args.append("--full-refresh")
        result, bundle = await self._invoke(
            context,
            args,
            operation="run_pipeline",
            effect=EffectSemantics.NON_IDEMPOTENT,
            selected=payload.select or (),
        )
        executed = self._execute_output(context, result, bundle, "run_pipeline")
        tests = (
            test_results_from_run_results(parse_run_results(bundle.run_results_path))
            if bundle.run_results_path is not None
            else ()
        )
        ok = executed.ok and all(item.status in {"pass", "warn"} for item in tests)
        return RunPipelineOutput(
            ok=ok, results=executed.results, tests=tests, run_results_ref=executed.run_results_ref
        )

    async def run_tests(self, payload: RunTestsInput, context: CallContext) -> RunTestsOutput:
        args = ["test", *self._select_args(payload.select), *self._project_args(context)]
        if payload.store_failures:
            args.append("--store-failures")
        effect = (
            EffectSemantics.NON_IDEMPOTENT
            if payload.store_failures
            else EffectSemantics.SIDE_EFFECT_FREE
        )
        result, bundle = await self._invoke(
            context,
            args,
            operation="run_tests",
            effect=effect,
            selected=payload.select or (),
        )
        tests = (
            test_results_from_run_results(parse_run_results(bundle.run_results_path))
            if bundle.run_results_path is not None
            else ()
        )
        provenance = self._provenance(context, "run_tests")
        ref = None
        if "run_results.json" in bundle.hashes:
            ref = artifact_ref(
                sha256=bundle.hashes["run_results.json"],
                artifact_type="run_results.json",
                provenance=provenance,
            )
        ok = result.exit_code == 0 and all(item.status in {"pass", "warn"} for item in tests)
        return RunTestsOutput(ok=ok, tests=tests, run_results_ref=ref)

    async def get_lineage(self, payload: GetLineageInput, context: CallContext) -> GetLineageOutput:
        project, _profiles, _duck = self._ensure_workspace(context.workflow_id)
        manifest_path = project / "target" / "manifest.json"
        found = find_latest_journal_for_operation(
            workflow_root(self.settings.work_root, context.workflow_id) / "invocations",
            context.operation_idempotency_key,
        )
        if found is not None:
            captured = found[0] / "target" / "manifest.json"
            if captured.exists():
                manifest_path = captured
        if payload.project_state_id is not None and payload.project_state_id in self._states:
            candidate = self._states[payload.project_state_id] / "target" / "manifest.json"
            if candidate.exists():
                manifest_path = candidate
        if not manifest_path.exists():
            raise DbtMappedError(FailureClass.CONNECTOR_FAILURE, "manifest.json not found")
        manifest = parse_manifest(manifest_path)
        nodes, edges = lineage_from_manifest(manifest)
        return GetLineageOutput(
            nodes=tuple(
                LineageNode(id=node["id"], kind=node["kind"], name=node["name"])  # type: ignore[arg-type]
                for node in nodes
            ),
            edges=tuple(
                LineageEdge(from_id=edge["from_id"], to_id=edge["to_id"]) for edge in edges
            ),
        )

    async def debug(self, context: CallContext) -> IsolatedResult:
        result, _bundle = await self._invoke(
            context,
            ["debug", *self._project_args(context)],
            operation="debug",
            effect=EffectSemantics.SIDE_EFFECT_FREE,
            selected=(),
        )
        return result

    async def parse(self, context: CallContext) -> IsolatedResult:
        result, _bundle = await self._invoke(
            context,
            ["parse", *self._project_args(context)],
            operation="parse",
            effect=EffectSemantics.SIDE_EFFECT_FREE,
            selected=(),
        )
        return result

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown:
        key = recovery.operation_idempotency_key
        found = find_latest_journal_for_operation(
            workflow_root(self.settings.work_root, recovery.workflow_id) / "invocations",
            key,
        )
        if recovery.capability.capability_id == "create_transformation":
            expected = self._written_hashes.get(key, dict(recovery.operation_locator))
            project = project_dir(self.settings.work_root, recovery.workflow_id)
            return reconcile_create_transformation(expected_hashes=expected, project_root=project)
        journal = found[1] if found is not None else None
        run_results = None
        manifest_present = False
        required: tuple[str, ...] = ()
        if found is not None:
            rr_path = found[0] / "target" / "run_results.json"
            manifest_path = found[0] / "target" / "manifest.json"
            manifest_present = manifest_path.exists()
            if rr_path.exists():
                run_results = parse_run_results(rr_path)
            if journal is not None:
                required = journal.selected_nodes
        return reconcile_invocation(
            journal=journal,
            run_results=run_results,
            manifest_present=manifest_present,
            required_nodes=required,
        )

    async def _invoke(
        self,
        context: CallContext,
        args: list[str],
        *,
        operation: str,
        effect: EffectSemantics,
        selected: tuple[str, ...],
    ) -> tuple[IsolatedResult, ArtifactBundle]:
        snapshot = await self.health()
        if snapshot.status == "UNAVAILABLE":
            raise DbtMappedError(
                FailureClass.CONNECTOR_FAILURE,
                ",".join(snapshot.reason_codes) or "connector unavailable",
            )
        project, profiles, duck = self._ensure_workspace(context.workflow_id)
        extra = {
            "AIDE_DBT_DUCKDB_PATH": str(duck),
            "DBT_PROFILES_DIR": str(profiles),
        }
        secret_names = self.settings.required_secret_names()
        env = build_controlled_env(extra, secret_names=secret_names)
        timeout = remaining_timeout_seconds(
            _seconds_until(context.deadline), self.settings.timeout_seconds
        )
        dest = invocation_dir(
            self.settings.work_root,
            context.workflow_id,
            context.operation_idempotency_key,
            context.attempt_id,
        )
        self._journal(
            context,
            operation=operation,
            status=DispatchStatus.DISPATCHED,
            selected=selected,
            hashes={},
            effect=effect,
            applied=False,
        )
        try:
            result = await asyncio.to_thread(
                run_dbt,
                args,
                work_root=self.settings.work_root,
                workflow_id=context.workflow_id,
                operation_idempotency_key=context.operation_idempotency_key,
                attempt_id=context.attempt_id,
                cwd=project,
                env=env,
                timeout_seconds=timeout,
                secret_names=secret_names,
            )
        except DbtTimeoutError:
            self._journal(
                context,
                operation=operation,
                status=DispatchStatus.TIMEOUT,
                selected=selected,
                hashes={},
                effect=effect,
                applied=False,
            )
            raise
        except DbtProcessTerminatedError:
            self._journal(
                context,
                operation=operation,
                status=DispatchStatus.TERMINATED,
                selected=selected,
                hashes={},
                effect=effect,
                applied=False,
            )
            raise
        status = DispatchStatus.COMPLETED if result.exit_code == 0 else DispatchStatus.FAILED
        bundle = capture_target_artifacts(
            project_dir=project,
            invocation_dir=dest,
            selected_nodes=selected,
            invocation_arguments=tuple(args),
            execution_status=status.value,
        )
        self._journal(
            context,
            operation=operation,
            status=status,
            selected=selected,
            hashes=bundle.hashes,
            effect=effect,
            applied=True,
            adapter_response={"exit_code": result.exit_code, "exception": result.result_payload},
        )
        return result, bundle

    def _execute_output(
        self,
        context: CallContext,
        result: IsolatedResult,
        bundle: ArtifactBundle,
        capability: str,
    ) -> ExecuteTransformationOutput:
        provenance = self._provenance(context, capability)
        results = (
            node_results_from_run_results(parse_run_results(bundle.run_results_path))
            if bundle.run_results_path is not None
            else ()
        )
        ref = None
        if "run_results.json" in bundle.hashes:
            ref = artifact_ref(
                sha256=bundle.hashes["run_results.json"],
                artifact_type="run_results.json",
                provenance=provenance,
            )
        ok = result.exit_code == 0 and all(
            item.status in {"success", "skipped"} for item in results
        )
        return ExecuteTransformationOutput(ok=ok, results=results, run_results_ref=ref)

    def _ensure_workspace(self, workflow_id: UUID) -> tuple[Path, Path, Path]:
        template = self.settings.project_template or default_project_template()
        project = ensure_project_copy(template, project_dir(self.settings.work_root, workflow_id))
        profiles = profiles_dir(self.settings.work_root, workflow_id)
        profiles.mkdir(parents=True, exist_ok=True)
        (profiles / "profiles.yml").write_text(
            render_profiles_yaml(self.settings), encoding="utf-8"
        )
        duck = duckdb_workspace_path(self.settings.work_root, workflow_id)
        if self.settings.adapter is DbtAdapter.DUCKDB and not duck.exists():
            source = self.settings.duckdb_path
            if source is None or not source.exists():
                raise DbtMappedError(
                    FailureClass.CONNECTOR_FAILURE,
                    "DuckDB fixture path is not configured",
                )
            duck.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, duck)
        return project, profiles, duck

    def _project_args(self, context: CallContext) -> list[str]:
        project, profiles, _duck = (
            project_dir(self.settings.work_root, context.workflow_id),
            profiles_dir(self.settings.work_root, context.workflow_id),
            duckdb_workspace_path(self.settings.work_root, context.workflow_id),
        )
        return [
            "--project-dir",
            str(project),
            "--profiles-dir",
            str(profiles),
            "--target",
            self.settings.target_name,
            "--no-use-colors",
        ]

    def _select_args(self, select: tuple[str, ...] | None) -> list[str]:
        if not select:
            return []
        return ["--select", *select]

    def _provenance(self, context: CallContext, capability_id: str) -> ArtifactProvenance:
        return provenance_for(
            is_fake=self.spec.is_fake,
            connector_id=self.spec.connector_id,
            connector_version=self.spec.version,
            capability_id=capability_id,
            operation_idempotency_key=context.operation_idempotency_key,
            resolved_input_digest=context.resolved_input_digest,
        )

    def _classify_result(self, result: IsolatedResult) -> FailureClass:
        name = result.result_payload.get("exception_type")
        message = str(result.result_payload.get("message") or result.stderr or result.stdout)
        if isinstance(name, str):
            return map_exception_name(name, message)
        return FailureClass.DBT_RUNTIME

    def _journal(
        self,
        context: CallContext,
        *,
        operation: str,
        status: DispatchStatus,
        selected: tuple[str, ...],
        hashes: dict[str, str],
        effect: EffectSemantics,
        applied: bool,
        adapter_response: dict[str, object] | None = None,
    ) -> None:
        dest = invocation_dir(
            self.settings.work_root,
            context.workflow_id,
            context.operation_idempotency_key,
            context.attempt_id,
        )
        append_journal(
            dest,
            InvocationJournalEntry(
                workflow_id=context.workflow_id,
                operation=operation,
                attempt_id=context.attempt_id,
                attempt_number=context.attempt_number,
                operation_idempotency_key=context.operation_idempotency_key,
                selected_nodes=selected,
                compiled_configuration={
                    "adapter": self.settings.adapter.value,
                    "target": self.settings.target_name,
                    "threads": self.settings.threads,
                    "profile": self.settings.profile_name,
                },
                dispatch_status=status,
                adapter_response=adapter_response,
                artifact_hashes=hashes,
                effect_semantics=effect,
                effect_applied=applied,
                recorded_at=utc_now_iso(),
            ),
        )


def _seconds_until(deadline: datetime) -> float:
    now = datetime.now(deadline.tzinfo) if deadline.tzinfo else datetime.now()
    return max(0.1, (deadline - now).total_seconds())


def _safe_message(result: IsolatedResult) -> str:
    raw = str(result.result_payload.get("message") or result.stderr or result.stdout)
    return raw[:400]


def build_real_duckdb(
    work_root: Path,
    *,
    duckdb_path: Path,
    project_template: Path | None = None,
) -> RealDbtConnector:
    return RealDbtConnector(
        DBT_DEV,
        duckdb_dbt_settings(
            work_root,
            duckdb_path=duckdb_path,
            project_template=project_template,
        ),
    )
