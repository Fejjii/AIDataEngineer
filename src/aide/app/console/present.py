"""Turn persisted run rows and allowlisted artifacts into a console page.

Missing sections stay unavailable. They are never rendered as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aide.app.console.snapshot import (
    BUSINESS_CORRECTNESS,
    EXECUTION_LABEL,
    LIMITATIONS,
    failure_messages,
)
from aide.persistence.console import SNAPSHOT_ARTIFACT_TYPE

_UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CheckView:
    name: str
    outcome: str
    detail: str


@dataclass(frozen=True)
class PreviewView:
    state: str
    relation: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    note: str


@dataclass(frozen=True)
class SqlFileView:
    path: str
    sql: str


@dataclass(frozen=True)
class WorkflowView:
    workflow_id: str
    control_plane_state: str
    benchmark_outcome: str
    fail_reason: str
    block_reason: str
    drift_state: str
    drift_mapping: str
    drift_hypothesis: str
    failure_messages: tuple[str, ...]
    repair_allowed: str
    repair_applied: str
    repair_path: str
    original_sql: str
    repaired_sql: str
    models: tuple[SqlFileView, ...]
    preview: PreviewView
    tests_state: str
    tests: tuple[CheckView, ...]
    aggregate_test_flag: str
    quality_state: str
    quality_checks: tuple[CheckView, ...]
    verifier_state: str
    verifier_verdict: str
    verifier_checks: tuple[CheckView, ...]


@dataclass(frozen=True)
class AuditEventView:
    workflow_id: str
    sequence: int
    event_type: str
    created_at: str


@dataclass(frozen=True)
class RunPage:
    run_id: str
    status: str
    error_message: str
    started_at: str
    finished_at: str
    execution_label: str
    business_correctness: str
    limitations: tuple[str, ...]
    benchmark_verdict: str
    determinism: str
    evidence_completeness: str
    evidence_complete: str
    workflows: tuple[WorkflowView, ...]
    audit_events: tuple[AuditEventView, ...]
    running_note: str


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    started_at: str
    finished_at: str
    workflow_count: int


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    body: bytes


def present_run(
    *,
    run_id: str,
    status: str,
    error_message: str | None,
    started_at: str,
    finished_at: str | None,
    workflow_ids: tuple[str, ...],
    control_plane_states: dict[str, str],
    artifacts: dict[str, dict[str, dict[str, Any]]],
    audit_events: tuple[AuditEventView, ...],
) -> RunPage:
    snapshot = _find_snapshot(artifacts)
    snapshot_workflows = _snapshot_workflows(snapshot)
    panels = tuple(
        _workflow_panel(
            workflow_id,
            control_plane_state=control_plane_states.get(workflow_id, _UNAVAILABLE),
            artifact_bodies=artifacts.get(workflow_id, {}),
            snapshot_workflow=snapshot_workflows.get(workflow_id),
        )
        for workflow_id in workflow_ids
    )
    return RunPage(
        run_id=run_id,
        status=status,
        error_message=error_message or "",
        started_at=started_at,
        finished_at=finished_at or "",
        execution_label=EXECUTION_LABEL,
        business_correctness=BUSINESS_CORRECTNESS,
        limitations=LIMITATIONS,
        benchmark_verdict=_text(snapshot, "benchmark_verdict"),
        determinism=_bool_text(snapshot, "determinism_equivalent"),
        evidence_completeness=_text(snapshot, "evidence_completeness_pct"),
        evidence_complete=_bool_text(snapshot, "evidence_complete"),
        workflows=panels,
        audit_events=audit_events,
        running_note=(
            "Running. The benchmark executes two workflows, one after the other. "
            "This page reads persisted status and audit events. It does not invent stages."
        ),
    )


def export_file(page: RunPage, name: str) -> ExportFile | None:
    """Build one allowlisted export from the first workflow panel."""
    if not page.workflows:
        return None
    panel = page.workflows[0]
    if name == "output-preview":
        return _preview_csv(panel.preview)
    if name == "original-sql":
        return _text_file("original.sql", "text/plain; charset=utf-8", panel.original_sql)
    if name == "repaired-sql":
        return _text_file("repaired.sql", "text/plain; charset=utf-8", panel.repaired_sql)
    if name == "generated-sql":
        if not panel.models:
            return None
        chunks = [f"-- {item.path}\n{item.sql}" for item in panel.models]
        return _text_file("generated.sql", "text/plain; charset=utf-8", "\n\n".join(chunks))
    if name == "quality":
        return _checks_json("quality.json", panel.quality_state, panel.quality_checks)
    if name == "verifier":
        if panel.verifier_state != "present":
            return None
        return _checks_json("verifier.json", panel.verifier_verdict, panel.verifier_checks)
    if name == "tests":
        return _checks_json("tests.json", panel.tests_state, panel.tests)
    return None


def _workflow_panel(
    workflow_id: str,
    *,
    control_plane_state: str,
    artifact_bodies: dict[str, dict[str, Any]],
    snapshot_workflow: dict[str, Any] | None,
) -> WorkflowView:
    proposal = artifact_bodies.get("repair_proposal")
    validation = artifact_bodies.get("repair_validation")
    application = artifact_bodies.get("repair_application")
    failure = artifact_bodies.get("original_failure")
    quality = artifact_bodies.get("quality_results")
    verifier = artifact_bodies.get("verifier_verdict")
    tests_flag = artifact_bodies.get("dbt_tests")
    snap = snapshot_workflow or {}
    return WorkflowView(
        workflow_id=workflow_id,
        control_plane_state=control_plane_state,
        benchmark_outcome=_snap_text(snap, "benchmark_outcome"),
        fail_reason=_snap_text(snap, "fail_reason"),
        block_reason=_snap_text(snap, "block_reason"),
        drift_state="present" if isinstance(proposal, dict) else _UNAVAILABLE,
        drift_mapping=_drift_mapping(proposal),
        drift_hypothesis=_short(proposal, "hypothesis"),
        failure_messages=failure_messages(failure),
        repair_allowed=_flag(validation, "allowed"),
        repair_applied=_flag(application, "applied"),
        repair_path=_short(proposal, "artifact_path"),
        original_sql=_snap_text(snap, "original_sql"),
        repaired_sql=_short(proposal, "patched_sql")
        if isinstance(proposal, dict)
        else _UNAVAILABLE,
        models=_models(snap.get("models")),
        preview=_preview(snap.get("output_preview")),
        tests_state="present" if _test_rows(snap.get("individual_tests")) else _UNAVAILABLE,
        tests=_test_rows(snap.get("individual_tests")),
        aggregate_test_flag=_flag(tests_flag, "ok"),
        quality_state="present"
        if isinstance(quality, dict) and "checks" in quality
        else _UNAVAILABLE,
        quality_checks=_quality_rows(quality),
        verifier_state="present" if _verdict(verifier) is not None else _UNAVAILABLE,
        verifier_verdict=_verdict(verifier) or _UNAVAILABLE,
        verifier_checks=_verifier_rows(verifier),
    )


def _find_snapshot(
    artifacts: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    for bodies in artifacts.values():
        body = bodies.get(SNAPSHOT_ARTIFACT_TYPE)
        if isinstance(body, dict) and body.get("schema_version") == 1:
            return body
    return None


def _snapshot_workflows(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if snapshot is None:
        return {}
    rows = snapshot.get("workflows")
    if not isinstance(rows, list):
        return {}
    found: dict[str, dict[str, Any]] = {}
    for item in rows:
        if isinstance(item, dict) and isinstance(item.get("workflow_id"), str):
            found[item["workflow_id"]] = item
    return found


def _models(value: object) -> tuple[SqlFileView, ...]:
    if not isinstance(value, list):
        return ()
    files: list[SqlFileView] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        sql = item.get("sql")
        if isinstance(path, str) and isinstance(sql, str) and path.startswith("models/"):
            files.append(SqlFileView(path=path, sql=sql))
    return tuple(files)


def _preview(value: object) -> PreviewView:
    empty = PreviewView(_UNAVAILABLE, "", (), (), "output preview unavailable")
    if not isinstance(value, dict):
        return empty
    columns = value.get("columns")
    rows = value.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return empty
    names = tuple(str(item) for item in columns)
    rendered: list[tuple[str, ...]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered.append(tuple(_cell(row.get(name)) for name in names))
    note = value.get("note")
    return PreviewView(
        state="present",
        relation=str(value.get("relation") or ""),
        columns=names,
        rows=tuple(rendered),
        note=str(note) if isinstance(note, str) else "",
    )


def _test_rows(value: object) -> tuple[CheckView, ...]:
    if not isinstance(value, list) or not value:
        return ()
    rows: list[CheckView] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        rows.append(
            CheckView(
                name=str(item.get("test_name") or "test"),
                outcome=str(item.get("status") or _UNAVAILABLE),
                detail=_test_detail(item),
            )
        )
    return tuple(rows)


def _test_detail(item: dict[str, Any]) -> str:
    model = item.get("model") or ""
    column = item.get("column") or ""
    failures = item.get("failures")
    return f"model={model} column={column} failures={failures}"


def _quality_rows(body: dict[str, Any] | None) -> tuple[CheckView, ...]:
    if not isinstance(body, dict) or not isinstance(body.get("checks"), list):
        return ()
    rows: list[CheckView] = []
    for item in body["checks"]:
        if not isinstance(item, dict) or "passed" not in item:
            continue
        rows.append(
            CheckView(
                name=str(item.get("check_id") or "check"),
                outcome="true" if item.get("passed") is True else "false",
                detail=str(item.get("detail") or "")[:240],
            )
        )
    return tuple(rows)


def _verifier_rows(body: dict[str, Any] | None) -> tuple[CheckView, ...]:
    if _verdict(body) is None or not isinstance(body, dict):
        return ()
    checks = body.get("checks")
    if not isinstance(checks, list):
        return ()
    rows: list[CheckView] = []
    for item in checks:
        if not isinstance(item, dict) or "passed" not in item:
            continue
        rows.append(
            CheckView(
                name=str(item.get("check_id") or "check"),
                outcome="true" if item.get("passed") is True else "false",
                detail=str(item.get("detail") or item.get("reason_code") or "")[:240],
            )
        )
    return tuple(rows)


def _verdict(body: dict[str, Any] | None) -> str | None:
    if not isinstance(body, dict):
        return None
    verdict = body.get("verdict")
    if verdict in {"PASS", "FAIL"}:
        return str(verdict)
    return None


def _drift_mapping(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        return _UNAVAILABLE
    source = body.get("from_column")
    target = body.get("to_column")
    if not isinstance(source, str) or not isinstance(target, str):
        return _UNAVAILABLE
    return f"{source} → {target}"


def _flag(body: dict[str, Any] | None, key: str) -> str:
    if not isinstance(body, dict) or key not in body:
        return _UNAVAILABLE
    value = body.get(key)
    if value is True:
        return "true"
    if value is False:
        return "false"
    return _UNAVAILABLE


def _short(body: dict[str, Any] | None, key: str) -> str:
    if not isinstance(body, dict):
        return _UNAVAILABLE
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        return _UNAVAILABLE
    text = value.strip()
    if len(text) > 8000:
        return text[:8000] + "\n-- truncated for display"
    return text


def _snap_text(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if value is None or value == "":
        return _UNAVAILABLE
    return str(value)


def _text(body: dict[str, Any] | None, key: str) -> str:
    if not isinstance(body, dict) or key not in body or body.get(key) in (None, ""):
        return _UNAVAILABLE
    return str(body[key])


def _bool_text(body: dict[str, Any] | None, key: str) -> str:
    if not isinstance(body, dict) or key not in body:
        return _UNAVAILABLE
    value = body.get(key)
    if value is True:
        return "true"
    if value is False:
        return "false"
    return _UNAVAILABLE


def _cell(value: object) -> str:
    if value is None:
        return "null"
    return str(value)


def _preview_csv(preview: PreviewView) -> ExportFile | None:
    if preview.state != "present":
        return None
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(preview.columns)
    for row in preview.rows:
        writer.writerow(tuple(_csv_cell(item) for item in row))
    return ExportFile("output-preview.csv", "text/csv; charset=utf-8", buffer.getvalue().encode())


def _csv_cell(value: str) -> str:
    if value[:1] in {"=", "+", "-", "@"}:
        return "'" + value
    return value


def _text_file(filename: str, media_type: str, content: str) -> ExportFile | None:
    if content == _UNAVAILABLE or not content.strip():
        return None
    body = content.encode("utf-8")
    if len(body) > 200_000:
        body = body[:200_000] + b"\n-- truncated\n"
    return ExportFile(filename, media_type, body)


def _checks_json(filename: str, state: str, checks: tuple[CheckView, ...]) -> ExportFile | None:
    if state == _UNAVAILABLE:
        return None
    import json

    payload = {
        "state": state,
        "checks": [
            {"name": item.name, "outcome": item.outcome, "detail": item.detail} for item in checks
        ],
    }
    return ExportFile(
        filename,
        "application/json",
        json.dumps(payload, indent=2).encode("utf-8"),
    )
