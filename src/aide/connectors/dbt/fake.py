"""Lightweight deterministic fake dbt connector for unit and recovery tests."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import duckdb
import yaml

from aide.capabilities.io import (
    ValidateInterviewQualityInput,
    ValidationReport,
)
from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.dbt.artifacts import (
    capture_target_artifacts,
    lineage_from_manifest,
    node_results_from_run_results,
    parse_manifest,
    parse_run_results,
    provenance_for,
    test_results_from_run_results,
)
from aide.connectors.dbt.contracts import (
    CompiledModel,
    CompileTransformationInput,
    CompileTransformationOutput,
    ConnectorArtifactRef,
    CreateTransformationInput,
    CreateTransformationOutput,
    ExecuteTransformationInput,
    ExecuteTransformationOutput,
    GetLineageInput,
    GetLineageOutput,
    LineageEdge,
    LineageNode,
    ParseTransformationInput,
    ParseTransformationOutput,
    RunPipelineInput,
    RunPipelineOutput,
    RunTestsInput,
    RunTestsOutput,
    TestNodeResult,
    TransformationIssue,
)
from aide.connectors.dbt.errors import DbtMappedError, map_error
from aide.connectors.dbt.journal import (
    DispatchStatus,
    InvocationJournalEntry,
    append_journal,
    find_latest_journal_for_operation,
    utc_now_iso,
)
from aide.connectors.dbt.namespace import workflow_short_id
from aide.connectors.dbt.reconcile import reconcile_create_transformation, reconcile_invocation
from aide.connectors.dbt.specs import FAKE_DBT_DEV
from aide.connectors.dbt.workspace import (
    default_project_template,
    ensure_project_copy,
    invocation_dir,
    project_dir,
    tiny_fixture_csv_root,
    workflow_root,
    write_project_files,
)
from aide.domain.effects import EffectSemantics
from aide.domain.failures import FailureClass

SOURCE_RE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
    re.I,
)
REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.I)
CONFIG_RE = re.compile(r"\{\{\s*config\s*\(.*?\)\s*\}\}", re.I | re.S)
SNOWFLAKE_TARGET_IF_RE = re.compile(
    r"\{%\s*if\s+target\.type\s*==\s*['\"]snowflake['\"]\s*%\}"
    r"(.*?)"
    r"\{%\s*else\s*%\}"
    r"(.*?)"
    r"\{%\s*endif\s*%\}",
    re.I | re.S,
)
SNOWFLAKE_IF_ENDIF_RE = re.compile(
    r"\{%\s*if\s+target\.type\s*==\s*['\"]snowflake['\"]\s*%\}"
    r"(.*?)"
    r"\{%\s*endif\s*%\}",
    re.I | re.S,
)

DEFAULT_SOURCE_RELATIONS = {
    ("vantara_raw", "customers"): '"VANTARA_RAW"."BILLING"."CUSTOMERS"',
    ("vantara_raw", "invoices"): '"VANTARA_RAW"."BILLING"."INVOICES"',
}
SOURCE_RELATIONS = DEFAULT_SOURCE_RELATIONS

HEALTH_TTL = timedelta(minutes=5)


class FakeDbtConnector:
    """Fixture-backed fake with the same handler set and reconcile as the real connector."""

    def __init__(
        self,
        spec: ConnectorSpec | None = None,
        *,
        work_root: Path,
        csv_root: Path | None = None,
        project_template: Path | None = None,
    ) -> None:
        self.spec = spec or FAKE_DBT_DEV
        self.work_root = Path(work_root)
        self.csv_root = csv_root or tiny_fixture_csv_root()
        self.project_template = project_template or default_project_template()
        self._conn = duckdb.connect(database=":memory:")
        self._fail_next: dict[str, FailureClass] = {}
        self._fail_after: set[str] = set()
        self._in_progress: set[str] = set()
        self._states: dict[UUID, Path] = {}
        self._written_hashes: dict[str, dict[str, str]] = {}
        self._outputs: dict[str, dict[str, Any]] = {}
        self._source_relations: dict[tuple[str, str], str] = dict(DEFAULT_SOURCE_RELATIONS)
        self._install_fixtures()

    def fail_next(self, capability: str, failure: FailureClass) -> None:
        self._fail_next[capability] = failure

    def fail_after_effect(self, capability: str) -> None:
        self._fail_after.add(capability)

    def mark_in_progress(self, operation_key: str) -> None:
        self._in_progress.add(operation_key)

    def rename_loaded_column(
        self,
        workflow_id: UUID,
        schema: str,
        table: str,
        from_name: str,
        to_name: str,
    ) -> None:
        """Rename one loaded DEV source column. Test/demo drift injection only."""
        short = workflow_short_id(workflow_id)
        qualified_schema = schema if schema.startswith(short) else f"{short}_{schema}"
        relation = f'"{qualified_schema}"."{table}"'
        description = self._conn.execute(f"SELECT * FROM {relation} LIMIT 0").description or []
        existing = [str(col[0]) for col in description]
        actual_from = next(
            (name for name in existing if name.upper() == from_name.upper()),
            from_name,
        )
        self._conn.execute(f'ALTER TABLE {relation} RENAME COLUMN "{actual_from}" TO "{to_name}"')

    async def health(self) -> ConnectorHealthSnapshot:
        now = datetime.now(UTC).replace(tzinfo=None)
        return ConnectorHealthSnapshot(
            connector_id=self.spec.connector_id,
            status="MOCK",
            checked_at=now,
            expires_at=now + HEALTH_TTL,
        )

    async def close(self) -> None:
        self._conn.close()

    async def create_transformation(
        self, payload: CreateTransformationInput, context: CallContext
    ) -> CreateTransformationOutput:
        self._maybe_fail("create_transformation")
        project = self._ensure_project(context.workflow_id)
        written = write_project_files(project, payload.files, mode=payload.mode)
        state_id = uuid4()
        self._states[state_id] = project
        hashes = {item.path: item.sha256 for item in written}
        self._written_hashes[context.operation_idempotency_key] = hashes
        output = CreateTransformationOutput(written=written, project_state_id=state_id)
        self._record_effect(
            context, "create_transformation", output.model_dump(mode="json"), hashes
        )
        self._write_journal(
            context,
            operation="create_transformation",
            status=DispatchStatus.COMPLETED,
            selected=(),
            hashes=hashes,
            effect=EffectSemantics.EXTERNALLY_DEDUPLICATED,
            applied=True,
        )
        if "create_transformation" in self._fail_after:
            self._fail_after.discard("create_transformation")
            raise DbtMappedError(FailureClass.CONNECTOR_FAILURE, "fail_after_effect")
        return output

    async def compile_transformation(
        self, payload: CompileTransformationInput, context: CallContext
    ) -> CompileTransformationOutput:
        self._maybe_fail("compile_transformation")
        project = self._project_for(payload.project_state_id, context.workflow_id)
        dest = invocation_dir(
            self.work_root,
            context.workflow_id,
            context.operation_idempotency_key,
            context.attempt_id,
        )
        try:
            manifest, compiled = self._compile_project(project, payload.select)
        except DbtMappedError as exc:
            self._write_journal(
                context,
                operation="compile_transformation",
                status=DispatchStatus.FAILED,
                selected=payload.select or (),
                hashes={},
                effect=EffectSemantics.SIDE_EFFECT_FREE,
                applied=False,
            )
            return CompileTransformationOutput(
                ok=False,
                errors=(TransformationIssue(message=str(exc), error_class=exc.failure),),
            )
        self._write_manifest(project, manifest)
        for name, sql in compiled.items():
            compiled_path = (
                project / "target" / "compiled" / "vantara_project" / "models" / f"{name}.sql"
            )
            compiled_path.parent.mkdir(parents=True, exist_ok=True)
            compiled_path.write_text(sql, encoding="utf-8")
        bundle = capture_target_artifacts(
            project_dir=project,
            invocation_dir=dest,
            selected_nodes=payload.select or tuple(compiled),
            invocation_arguments=("compile",),
            execution_status="COMPLETED",
        )
        provenance = provenance_for(
            is_fake=True,
            connector_id=self.spec.connector_id,
            connector_version=self.spec.version,
            capability_id="compile_transformation",
            operation_idempotency_key=context.operation_idempotency_key,
            resolved_input_digest=context.resolved_input_digest,
        )
        manifest_ref = None
        if bundle.manifest_path is not None:
            manifest_ref = ConnectorArtifactRef(
                artifact_id=uuid4(),
                sha256=bundle.hashes["manifest.json"],
                type="manifest.json",
                provenance=provenance,
            )
        output = CompileTransformationOutput(
            ok=True,
            manifest_ref=manifest_ref,
            compiled=tuple(
                CompiledModel(model=name, compiled_sql=sql) for name, sql in compiled.items()
            ),
        )
        self._record_effect(
            context,
            "compile_transformation",
            output.model_dump(mode="json"),
            bundle.hashes,
        )
        self._write_journal(
            context,
            operation="compile_transformation",
            status=DispatchStatus.COMPLETED,
            selected=payload.select or tuple(compiled),
            hashes=bundle.hashes,
            effect=EffectSemantics.SIDE_EFFECT_FREE,
            applied=True,
        )
        return output

    async def execute_transformation(
        self, payload: ExecuteTransformationInput, context: CallContext
    ) -> ExecuteTransformationOutput:
        return await self._run_models(
            context,
            capability="execute_transformation",
            select=payload.select,
            project_state_id=payload.project_state_id,
            include_tests=False,
        )

    async def run_pipeline(
        self, payload: RunPipelineInput, context: CallContext
    ) -> RunPipelineOutput:
        executed = await self._run_models(
            context,
            capability="run_pipeline",
            select=payload.select or (),
            project_state_id=payload.project_state_id,
            include_tests=True,
        )
        stored = self._outputs.get(context.operation_idempotency_key) or {}
        tests = test_results_from_run_results(stored.get("run_results") or {"results": []})
        return RunPipelineOutput(
            ok=executed.ok and all(item.status in {"pass", "warn"} for item in tests),
            results=executed.results,
            tests=tests,
            run_results_ref=executed.run_results_ref,
        )

    async def run_tests(self, payload: RunTestsInput, context: CallContext) -> RunTestsOutput:
        self._maybe_fail("run_tests")
        project = self._project_for(payload.project_state_id, context.workflow_id)
        results, run_results = self._execute_tests(project, payload.select)
        dest = invocation_dir(
            self.work_root,
            context.workflow_id,
            context.operation_idempotency_key,
            context.attempt_id,
        )
        self._write_run_results(project, run_results)
        bundle = capture_target_artifacts(
            project_dir=project,
            invocation_dir=dest,
            selected_nodes=payload.select or (),
            invocation_arguments=("test",),
            execution_status="COMPLETED",
        )
        ok = all(item.status in {"pass", "warn"} for item in results)
        provenance = provenance_for(
            is_fake=True,
            connector_id=self.spec.connector_id,
            connector_version=self.spec.version,
            capability_id="run_tests",
            operation_idempotency_key=context.operation_idempotency_key,
            resolved_input_digest=context.resolved_input_digest,
        )
        ref = ConnectorArtifactRef(
            artifact_id=uuid4(),
            sha256=bundle.hashes.get("run_results.json", "0" * 64),
            type="run_results.json",
            provenance=provenance,
        )
        output = RunTestsOutput(ok=ok, tests=results, run_results_ref=ref)
        dumped = output.model_dump(mode="json")
        dumped["run_results"] = run_results
        self._record_effect(context, "run_tests", dumped, bundle.hashes)
        self._write_journal(
            context,
            operation="run_tests",
            status=DispatchStatus.COMPLETED,
            selected=payload.select or (),
            hashes=bundle.hashes,
            effect=EffectSemantics.SIDE_EFFECT_FREE
            if not payload.store_failures
            else EffectSemantics.NON_IDEMPOTENT,
            applied=True,
        )
        if "run_tests" in self._fail_after:
            self._fail_after.discard("run_tests")
            raise DbtMappedError(FailureClass.CONNECTOR_FAILURE, "fail_after_effect")
        return output

    async def get_lineage(self, payload: GetLineageInput, context: CallContext) -> GetLineageOutput:
        found = find_latest_journal_for_operation(
            workflow_root(self.work_root, context.workflow_id) / "invocations",
            context.operation_idempotency_key,
        )
        project = self._ensure_project(context.workflow_id)
        if payload.project_state_id is not None and payload.project_state_id in self._states:
            project = self._states[payload.project_state_id]
        manifest_path = project / "target" / "manifest.json"
        if found is not None:
            captured = found[0] / "target" / "manifest.json"
            if captured.exists():
                manifest_path = captured
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

    async def parse_transformation(
        self, payload: ParseTransformationInput, context: CallContext
    ) -> ParseTransformationOutput:
        self._maybe_fail("parse_transformation")
        project = self._project_for(payload.project_state_id, context.workflow_id)
        sources_path = project / "models" / "sources.yml"
        if sources_path.is_file():
            rendered = _render_target_jinja(sources_path.read_text(encoding="utf-8"))
            if "{{" in rendered or "{%" in rendered:
                return ParseTransformationOutput(
                    ok=False,
                    errors=(
                        TransformationIssue(
                            message="unresolved jinja in sources.yml",
                            error_class=FailureClass.DBT_COMPILE,
                        ),
                    ),
                )
            parsed = yaml.safe_load(rendered) or {}
            if isinstance(parsed, dict):
                self._ingest_sources(parsed)
        for path in sorted((project / "models").rglob("*.sql")):
            sql = _render_target_jinja(path.read_text(encoding="utf-8"))
            sql = CONFIG_RE.sub("", sql)
            sql = SOURCE_RE.sub("src", sql)
            sql = REF_RE.sub("ref", sql)
            if "{{" in sql or "{%" in sql:
                return ParseTransformationOutput(
                    ok=False,
                    errors=(
                        TransformationIssue(
                            model=path.stem,
                            message=f"unresolved jinja in {path.name}",
                            error_class=FailureClass.DBT_COMPILE,
                        ),
                    ),
                )
        self._write_journal(
            context,
            operation="parse_transformation",
            status=DispatchStatus.COMPLETED,
            selected=(),
            hashes={},
            effect=EffectSemantics.SIDE_EFFECT_FREE,
            applied=True,
        )
        return ParseTransformationOutput(ok=True)

    async def validate_interview_quality(
        self,
        payload: ValidateInterviewQualityInput,
        context: CallContext,
    ) -> ValidationReport:
        from aide.modelling.constants import REQUIRED_DEMO_MODELS
        from aide.quality.interview import evaluate_interview_quality

        self._maybe_fail("validate_interview_quality")
        models = payload.required_models or REQUIRED_DEMO_MODELS
        report = evaluate_interview_quality(self._conn.execute, required_models=models)
        assert isinstance(report, ValidationReport)
        self._write_journal(
            context,
            operation="validate_interview_quality",
            status=DispatchStatus.COMPLETED,
            selected=models,
            hashes={},
            effect=EffectSemantics.SIDE_EFFECT_FREE,
            applied=True,
        )
        return report

    def ensure_workflow_sources(self, payload: object, context: CallContext) -> None:
        from aide.capabilities.io import LoadManifestSourcesInput
        from aide.connectors.snowflake.manifest import load_csvs_into_dev, verify_pinned_manifest

        assert isinstance(payload, LoadManifestSourcesInput)
        verify_pinned_manifest(payload.manifest_sha256)
        load_csvs_into_dev(
            self._conn,
            workflow_id=context.workflow_id,
            version=payload.fixture_version,
            selected=payload.selected_addresses,
            flattened=False,
        )
        short = workflow_short_id(context.workflow_id)
        for _database, schema, table in payload.selected_addresses:
            self._source_relations[(schema.lower(), table.lower())] = (
                f'"{short}_{schema}"."{table}"'
            )

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown:
        key = recovery.operation_idempotency_key
        if key in self._in_progress:
            return InProgress(external_ref=key, retry_after_seconds=5)
        found = find_latest_journal_for_operation(
            workflow_root(self.work_root, recovery.workflow_id) / "invocations",
            key,
        )
        journal = found[1] if found is not None else None
        if recovery.capability.capability_id == "create_transformation":
            expected = self._written_hashes.get(key, {})
            if not expected and recovery.operation_locator:
                expected = dict(recovery.operation_locator)
            project = project_dir(self.work_root, recovery.workflow_id)
            return reconcile_create_transformation(expected_hashes=expected, project_root=project)
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

    async def _run_models(
        self,
        context: CallContext,
        *,
        capability: str,
        select: tuple[str, ...],
        project_state_id: UUID,
        include_tests: bool,
    ) -> ExecuteTransformationOutput:
        self._maybe_fail(capability)
        project = self._project_for(project_state_id, context.workflow_id)
        dest = invocation_dir(
            self.work_root,
            context.workflow_id,
            context.operation_idempotency_key,
            context.attempt_id,
        )
        self._write_journal(
            context,
            operation=capability,
            status=DispatchStatus.DISPATCHED,
            selected=select,
            hashes={},
            effect=EffectSemantics.NON_IDEMPOTENT,
            applied=False,
        )
        manifest, compiled = self._compile_project(project, select or None)
        self._write_manifest(project, manifest)
        results: list[dict[str, Any]] = []
        for name in self._execution_order(manifest, compiled):
            if select and name not in select and f"model.vantara_project.{name}" not in select:
                continue
            sql = compiled[name]
            started = datetime.now(UTC)
            try:
                kind = "VIEW" if name.startswith("stg_") else "TABLE"
                self._conn.execute('CREATE SCHEMA IF NOT EXISTS "AIDE_DEV"')
                self._conn.execute(f'CREATE OR REPLACE {kind} "AIDE_DEV"."{name}" AS {sql}')
                status = "success"
                message = None
                error_class = None
            except Exception as exc:
                status = "error"
                message = str(exc)
                error_class = map_error(exc)
            elapsed = (datetime.now(UTC) - started).total_seconds()
            results.append(
                {
                    "unique_id": f"model.vantara_project.{name}",
                    "name": name,
                    "status": status,
                    "execution_time": elapsed,
                    "message": message,
                    "adapter_response": {"rows_affected": None},
                    "error_class": error_class.value if error_class else None,
                }
            )
        if include_tests:
            test_results, _payload = self._execute_tests(project, select or None)
            del test_results
            results.extend(_payload["results"])
        run_results = {
            "metadata": {"adapter_type": "duckdb", "dbt_version": "fake"},
            "results": results,
            "elapsed_time": 0.01,
        }
        self._write_run_results(project, run_results)
        bundle = capture_target_artifacts(
            project_dir=project,
            invocation_dir=dest,
            selected_nodes=select,
            invocation_arguments=(capability,),
            execution_status="COMPLETED",
        )
        provenance = provenance_for(
            is_fake=True,
            connector_id=self.spec.connector_id,
            connector_version=self.spec.version,
            capability_id=capability,
            operation_idempotency_key=context.operation_idempotency_key,
            resolved_input_digest=context.resolved_input_digest,
        )
        output = ExecuteTransformationOutput(
            ok=all(
                item["status"] == "success"
                for item in results
                if str(item["unique_id"]).startswith("model.")
            ),
            results=node_results_from_run_results(run_results),
            run_results_ref=ConnectorArtifactRef(
                artifact_id=uuid4(),
                sha256=bundle.hashes.get("run_results.json", "0" * 64),
                type="run_results.json",
                provenance=provenance,
            ),
        )
        dumped = output.model_dump(mode="json")
        dumped["run_results"] = run_results
        self._record_effect(context, capability, dumped, bundle.hashes)
        self._write_journal(
            context,
            operation=capability,
            status=DispatchStatus.COMPLETED,
            selected=select or tuple(compiled),
            hashes=bundle.hashes,
            effect=EffectSemantics.NON_IDEMPOTENT,
            applied=True,
            adapter_response={"nodes": len(results)},
        )
        if capability in self._fail_after:
            self._fail_after.discard(capability)
            raise DbtMappedError(FailureClass.CONNECTOR_FAILURE, "fail_after_effect")
        return output

    def _compile_project(
        self, project: Path, select: tuple[str, ...] | None
    ) -> tuple[dict[str, Any], dict[str, str]]:
        models = sorted((project / "models").rglob("*.sql"))
        compiled: dict[str, str] = {}
        nodes: dict[str, Any] = {}
        sources: dict[str, Any] = {}
        for source_name, table in self._source_relations:
            uid = f"source.vantara_project.{source_name}.{table}"
            sources[uid] = {"name": table, "resource_type": "source", "source_name": source_name}
        for path in models:
            name = path.stem
            if select and name not in select and f"model.vantara_project.{name}" not in select:
                continue
            raw = path.read_text(encoding="utf-8")
            sql = self._resolve_sql(raw)
            compiled[name] = sql
            depends = [f"source.vantara_project.{a}.{b}" for a, b in SOURCE_RE.findall(raw)]
            depends.extend(f"model.vantara_project.{item}" for item in REF_RE.findall(raw))
            uid = f"model.vantara_project.{name}"
            nodes[uid] = {
                "unique_id": uid,
                "name": name,
                "resource_type": "model",
                "compiled": True,
                "compiled_code": sql,
                "depends_on": {"nodes": depends},
            }
        manifest = {
            "metadata": {
                "adapter_type": "duckdb",
                "dbt_version": "fake",
                "project_name": "vantara_project",
            },
            "nodes": nodes,
            "sources": sources,
        }
        return manifest, compiled

    def _ingest_sources(self, payload: dict[str, Any]) -> None:
        for source in payload.get("sources") or []:
            if not isinstance(source, dict):
                continue
            name = str(source.get("name") or "")
            schema = str(source.get("schema") or "")
            if not name or not schema:
                continue
            for table in source.get("tables") or []:
                if not isinstance(table, dict):
                    continue
                table_name = str(table.get("name") or "")
                ident = str(table.get("identifier") or table_name)
                if table_name:
                    self._source_relations[(name, table_name)] = f'"{schema}"."{ident}"'

    def _resolve_sql(self, raw: str) -> str:
        sql = _render_target_jinja(raw)
        sql = CONFIG_RE.sub("", sql)

        def source_sub(match: re.Match[str]) -> str:
            key = (match.group(1), match.group(2))
            if key not in self._source_relations:
                raise DbtMappedError(FailureClass.DBT_COMPILE, f"unknown source {key}")
            return self._source_relations[key]

        def ref_sub(match: re.Match[str]) -> str:
            return f'"AIDE_DEV"."{match.group(1)}"'

        sql = SOURCE_RE.sub(source_sub, sql)
        sql = REF_RE.sub(ref_sub, sql)
        if "{{" in sql:
            raise DbtMappedError(FailureClass.DBT_COMPILE, "unresolved jinja")
        return sql.strip()

    def _execution_order(self, manifest: dict[str, Any], compiled: dict[str, str]) -> list[str]:
        nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), dict) else {}
        remaining = set(compiled)
        ordered: list[str] = []
        while remaining:
            ready: list[str] = []
            for name in sorted(remaining):
                uid = f"model.vantara_project.{name}"
                node = nodes.get(uid) if isinstance(nodes, dict) else None
                depends_raw = node.get("depends_on") if isinstance(node, dict) else {}
                depends = depends_raw if isinstance(depends_raw, dict) else {}
                refs = [
                    str(dep).split(".")[-1]
                    for dep in (depends.get("nodes") or [])
                    if str(dep).startswith("model.")
                ]
                if all(dep not in remaining for dep in refs):
                    ready.append(name)
            if not ready:
                ordered.extend(sorted(remaining))
                break
            ordered.extend(ready)
            remaining -= set(ready)
        return ordered

    def _execute_tests(
        self, project: Path, select: tuple[str, ...] | None
    ) -> tuple[Any, dict[str, Any]]:
        schema_path = project / "models" / "schema.yml"
        tests: list[dict[str, Any]] = []
        if schema_path.exists():
            payload = yaml.safe_load(schema_path.read_text(encoding="utf-8")) or {}
            for model in payload.get("models") or []:
                model_name = str(model.get("name"))
                if select and model_name not in select:
                    continue
                for column in model.get("columns") or []:
                    column_name = str(column.get("name"))
                    for test in column.get("tests") or []:
                        kind = test if isinstance(test, str) else next(iter(test))
                        status, failures = self._generic_test(model_name, column_name, str(kind))
                        tests.append(
                            {
                                "unique_id": (
                                    f"test.vantara_project.{kind}_{model_name}_{column_name}"
                                ),
                                "name": f"{kind}_{model_name}_{column_name}",
                                "status": status,
                                "failures": failures,
                                "execution_time": 0.01,
                                "depends_on": {"nodes": [f"model.vantara_project.{model_name}"]},
                            }
                        )
        parsed = tuple(
            TestNodeResult(
                test_name=str(item["name"]),
                model=str(item["depends_on"]["nodes"][0].split(".")[-1]),
                column=None,
                status=item["status"],
                failures=int(item["failures"]) if item.get("failures") is not None else None,
            )
            for item in tests
        )
        run_results = {
            "metadata": {"adapter_type": "duckdb", "dbt_version": "fake"},
            "results": tests,
            "elapsed_time": 0.01,
        }
        return parsed, run_results

    def _generic_test(self, model: str, column: str, kind: str) -> tuple[str, int]:
        ident = f'"AIDE_DEV"."{model}"'
        try:
            if kind == "not_null":
                row = self._conn.execute(
                    f'SELECT COUNT(*) FROM {ident} WHERE "{column}" IS NULL'
                ).fetchone()
            elif kind == "unique":
                row = self._conn.execute(
                    f'SELECT COUNT(*) FROM (SELECT "{column}" FROM {ident} '
                    f"GROUP BY 1 HAVING COUNT(*) > 1)"
                ).fetchone()
            else:
                return "error", 0
        except Exception:
            return "error", 0
        failures = int(row[0]) if row is not None else 0
        return ("fail" if failures else "pass"), failures

    def _install_fixtures(self) -> None:
        # DuckDB 1.5 treats a.b as catalog.schema. Attach an in-memory catalog so
        # Snowflake-style "VANTARA_RAW"."BILLING"."TABLE" identifiers resolve.
        self._conn.execute("ATTACH ':memory:' AS VANTARA_RAW")
        self._conn.execute('CREATE SCHEMA IF NOT EXISTS "VANTARA_RAW"."BILLING"')
        customers = self.csv_root / "billing" / "customers.csv"
        invoices = self.csv_root / "billing" / "invoices.csv"
        self._conn.execute(
            (
                'CREATE TABLE "VANTARA_RAW"."BILLING"."CUSTOMERS" '
                "AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)"
            ),
            [str(customers)],
        )
        self._conn.execute(
            (
                'CREATE TABLE "VANTARA_RAW"."BILLING"."INVOICES" '
                "AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)"
            ),
            [str(invoices)],
        )

    def _ensure_project(self, workflow_id: UUID) -> Path:
        dest = project_dir(self.work_root, workflow_id)
        return ensure_project_copy(self.project_template, dest)

    def _project_for(self, project_state_id: UUID, workflow_id: UUID) -> Path:
        return self._states.get(project_state_id) or self._ensure_project(workflow_id)

    def _maybe_fail(self, capability: str) -> None:
        failure = self._fail_next.pop(capability, None)
        if failure is not None:
            raise DbtMappedError(failure, f"injected {failure.value}")

    def _write_manifest(self, project: Path, manifest: dict[str, Any]) -> None:
        path = project / "target" / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def _write_run_results(self, project: Path, payload: dict[str, Any]) -> None:
        path = project / "target" / "run_results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _record_effect(
        self, context: CallContext, capability: str, output: dict[str, Any], hashes: dict[str, str]
    ) -> None:
        self._outputs[context.operation_idempotency_key] = {
            "capability": capability,
            "output": output,
            "run_results": output.get("run_results"),
            "hashes": hashes,
        }

    def _write_journal(
        self,
        context: CallContext,
        *,
        operation: str,
        status: DispatchStatus,
        selected: tuple[str, ...],
        hashes: dict[str, str],
        effect: EffectSemantics,
        applied: bool,
        adapter_response: dict[str, Any] | None = None,
    ) -> None:
        dest = invocation_dir(
            self.work_root,
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
                compiled_configuration={"adapter": "duckdb", "fake": True},
                dispatch_status=status,
                adapter_response=adapter_response,
                artifact_hashes=hashes,
                effect_semantics=effect,
                effect_applied=applied,
                recorded_at=utc_now_iso(),
            ),
        )


def _render_target_jinja(raw: str, *, target_type: str = "duckdb") -> str:
    snowflake = target_type.lower() == "snowflake"

    def if_else(match: re.Match[str]) -> str:
        return match.group(1) if snowflake else match.group(2)

    def if_endif(match: re.Match[str]) -> str:
        return match.group(1) if snowflake else ""

    rendered = SNOWFLAKE_TARGET_IF_RE.sub(if_else, raw)
    return SNOWFLAKE_IF_ENDIF_RE.sub(if_endif, rendered)
