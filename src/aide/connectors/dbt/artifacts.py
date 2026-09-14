"""Capture and parse dbt artifacts without secrets."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from aide.connectors.dbt.contracts import ConnectorArtifactRef, NodeRunResult, TestNodeResult
from aide.connectors.dbt.errors import map_run_result_status
from aide.connectors.dbt.redaction import sanitize_text
from aide.connectors.dbt.workspace import file_sha256
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.failures import FailureClass

MANIFEST_NAME = "manifest.json"
RUN_RESULTS_NAME = "run_results.json"


class ArtifactBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    invocation_dir: Path
    manifest_path: Path | None = None
    run_results_path: Path | None = None
    compiled_sql_paths: tuple[Path, ...] = ()
    hashes: dict[str, str] = Field(default_factory=dict)
    selected_nodes: tuple[str, ...] = ()
    invocation_arguments: tuple[str, ...] = ()
    execution_status: str = "UNKNOWN"


def capture_target_artifacts(
    *,
    project_dir: Path,
    invocation_dir: Path,
    selected_nodes: tuple[str, ...] = (),
    invocation_arguments: tuple[str, ...] = (),
    execution_status: str,
) -> ArtifactBundle:
    invocation_dir.mkdir(parents=True, exist_ok=True)
    source_target = project_dir / "target"
    dest_target = invocation_dir / "target"
    if source_target.exists():
        if dest_target.exists():
            shutil.rmtree(dest_target)
        shutil.copytree(source_target, dest_target)
    manifest = dest_target / MANIFEST_NAME if (dest_target / MANIFEST_NAME).exists() else None
    run_results = (
        dest_target / RUN_RESULTS_NAME if (dest_target / RUN_RESULTS_NAME).exists() else None
    )
    compiled = tuple(
        sorted((dest_target / "compiled").rglob("*.sql")) if dest_target.exists() else ()
    )
    hashes: dict[str, str] = {}
    if manifest is not None:
        hashes[MANIFEST_NAME] = file_sha256(manifest)
    if run_results is not None:
        hashes[RUN_RESULTS_NAME] = file_sha256(run_results)
    for compiled_path in compiled:
        rel = compiled_path.relative_to(dest_target).as_posix()
        hashes[rel] = file_sha256(compiled_path)
    capture = {
        "selected_nodes": list(selected_nodes),
        "invocation_arguments": list(invocation_arguments),
        "execution_status": execution_status,
        "artifact_hashes": hashes,
    }
    (invocation_dir / "invocation.json").write_text(
        json.dumps(capture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ArtifactBundle(
        invocation_dir=invocation_dir,
        manifest_path=manifest,
        run_results_path=run_results,
        compiled_sql_paths=compiled,
        hashes=hashes,
        selected_nodes=selected_nodes,
        invocation_arguments=invocation_arguments,
        execution_status=execution_status,
    )


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return payload


def parse_manifest(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if "nodes" not in payload:
        raise ValueError("manifest.json missing nodes")
    return payload


def parse_run_results(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if "results" not in payload:
        raise ValueError("run_results.json missing results")
    return payload


def selected_nodes_from_manifest(
    manifest: dict[str, Any], select: tuple[str, ...] | None
) -> tuple[str, ...]:
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return ()
    model_ids = tuple(
        sorted(str(uid) for uid, node in nodes.items() if _resource_type(node) == "model")
    )
    if not select:
        return model_ids
    wanted = set(select)
    matched: list[str] = []
    for unique_id in model_ids:
        node = nodes[unique_id]
        name = str(node.get("name", ""))
        if unique_id in wanted or name in wanted:
            matched.append(unique_id)
    return tuple(matched)


def _resource_type(node: object) -> str:
    if isinstance(node, dict):
        return str(node.get("resource_type", ""))
    return ""


def compiled_sql_from_manifest(manifest: dict[str, Any]) -> dict[str, str]:
    compiled: dict[str, str] = {}
    nodes = manifest.get("nodes")
    if not isinstance(nodes, dict):
        return compiled
    for unique_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        if node.get("resource_type") != "model":
            continue
        sql = node.get("compiled_code") or node.get("compiled_sql")
        if isinstance(sql, str) and sql.strip():
            compiled[str(unique_id)] = sql
    return compiled


def artifact_ref(
    *,
    sha256: str,
    artifact_type: str,
    provenance: ArtifactProvenance,
) -> ConnectorArtifactRef:
    return ConnectorArtifactRef(
        artifact_id=uuid4(),
        sha256=sha256,
        type=artifact_type,
        provenance=provenance,
    )


def provenance_for(
    *,
    is_fake: bool,
    connector_id: str,
    connector_version: str,
    capability_id: str,
    operation_idempotency_key: str,
    resolved_input_digest: str,
    parent_artifact_ids: tuple[UUID, ...] = (),
) -> ArtifactProvenance:
    return ArtifactProvenance(
        execution_mode=ExecutionMode.MOCK if is_fake else ExecutionMode.REAL,
        connector_id=connector_id,
        connector_version=connector_version,
        capability_id=capability_id,
        capability_version=1,
        operation_idempotency_key=operation_idempotency_key,
        resolved_input_digest=resolved_input_digest,
        parent_artifact_ids=parent_artifact_ids,
    )


def write_text_artifact(path: Path, text: str, *, extra_secrets: tuple[str, ...] = ()) -> str:
    sanitized = sanitize_text(text, extra_secrets=extra_secrets)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sanitized, encoding="utf-8")
    return file_sha256(path)


def node_results_from_run_results(payload: dict[str, Any]) -> tuple[NodeRunResult, ...]:
    parsed: list[NodeRunResult] = []
    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue
        unique_id = str(item.get("unique_id", ""))
        resource = unique_id.split(".", 1)[0]
        if resource not in {"model", "seed", "snapshot"}:
            continue
        status_raw = str(item.get("status", "error")).lower()
        status: str = "success"
        if status_raw in {"error", "fail"}:
            status = "error"
        elif status_raw == "skipped":
            status = "skipped"
        message = item.get("message")
        adapter_raw = item.get("adapter_response")
        adapter = adapter_raw if isinstance(adapter_raw, dict) else {}
        rows = adapter.get("rows_affected") if isinstance(adapter, dict) else None
        raw_class = item.get("error_class")
        error_class = None
        if isinstance(raw_class, str) and raw_class:
            try:
                error_class = FailureClass(raw_class)
            except ValueError:
                error_class = None
        if error_class is None:
            error_class = map_run_result_status(status_raw, str(message) if message else None)
        parsed.append(
            NodeRunResult(
                model=str(item.get("name") or unique_id.split(".")[-1]),
                status=status,  # type: ignore[arg-type]
                execution_time_s=float(item.get("execution_time") or 0.0),
                rows_affected=int(rows) if isinstance(rows, int) else None,
                message=str(message) if message is not None else None,
                error_class=error_class,
            )
        )
    return tuple(parsed)


def test_results_from_run_results(payload: dict[str, Any]) -> tuple[TestNodeResult, ...]:
    parsed: list[TestNodeResult] = []
    for item in payload.get("results", []):
        if not isinstance(item, dict):
            continue
        unique_id = str(item.get("unique_id", ""))
        if not unique_id.startswith("test."):
            continue
        status_raw = str(item.get("status", "error")).lower()
        status = status_raw if status_raw in {"pass", "fail", "warn", "error"} else "error"
        parsed.append(
            TestNodeResult(
                test_name=str(item.get("name") or unique_id.split(".")[-1]),
                model=_test_model_name(item),
                column=None,
                status=status,  # type: ignore[arg-type]
                failures=int(item["failures"]) if isinstance(item.get("failures"), int) else None,
            )
        )
    return tuple(parsed)


def _test_model_name(item: dict[str, Any]) -> str | None:
    depends = item.get("depends_on")
    if isinstance(depends, dict):
        nodes = depends.get("nodes")
        if isinstance(nodes, list) and nodes:
            first = str(nodes[0])
            return first.split(".")[-1]
    return None


def lineage_from_manifest(
    manifest: dict[str, Any],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    nodes_out: list[dict[str, str]] = []
    edges: list[dict[str, str]] = []
    nodes = manifest.get("nodes")
    sources = manifest.get("sources")
    if isinstance(sources, dict):
        for unique_id, node in sources.items():
            if isinstance(node, dict):
                nodes_out.append(
                    {
                        "id": str(unique_id),
                        "kind": "source",
                        "name": str(node.get("name", unique_id)),
                    }
                )
    if isinstance(nodes, dict):
        for unique_id, node in nodes.items():
            if not isinstance(node, dict):
                continue
            kind = str(node.get("resource_type", "model"))
            if kind not in {"model", "seed", "snapshot", "test", "source"}:
                continue
            nodes_out.append(
                {
                    "id": str(unique_id),
                    "kind": kind,
                    "name": str(node.get("name", unique_id)),
                }
            )
            depends = node.get("depends_on")
            if isinstance(depends, dict):
                for parent in depends.get("nodes") or []:
                    edges.append({"from_id": str(parent), "to_id": str(unique_id)})
    return nodes_out, edges
