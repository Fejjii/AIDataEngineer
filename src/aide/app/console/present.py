"""Turn persisted run rows and allowlisted artifacts into a console page.

Missing sections stay unavailable. They are never rendered as a pass, and no
count on the page is computed from anything other than persisted evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from aide.app.console.snapshot import (
    BUSINESS_CORRECTNESS,
    EXECUTION_LABEL,
    LIMITATIONS,
    READABLE_SNAPSHOT_VERSIONS,
    failure_messages,
)
from aide.persistence.console import SNAPSHOT_ARTIFACT_TYPE

_UNAVAILABLE = "unavailable"
_PRESENT = "present"
_COMPLETE = "complete"
_ISSUE = "issue"

_RECONCILIATION_CHECK_IDS = frozenset({"invoice_line_sum_matches_mart", "payment_sum_matches_mart"})
_MAX_PREVIEW_ROWS = 8
_ACTIVITY_COLUMNS = ("paid_amount", "refunded_amount", "net_paid_amount")


@dataclass(frozen=True)
class CheckView:
    name: str
    outcome: str
    detail: str


@dataclass(frozen=True)
class MetricView:
    key: str
    label: str
    value: str
    note: str = ""
    group: str = "primary"


@dataclass(frozen=True)
class SignalView:
    """One of the three judgements a completed run must keep separate."""

    key: str
    label: str
    value: str
    detail: str


@dataclass(frozen=True)
class SqlLineView:
    text: str
    changed: bool


@dataclass(frozen=True)
class StageView:
    """One step of the engineering loop, populated from evidence only."""

    key: str
    title: str
    state: str
    detail: str
    href: str


@dataclass(frozen=True)
class TwinView:
    state: str
    snapshot_id: str
    manifest_sha256: str
    estate_context_sha256: str
    pinned_asset_count: str
    selected_assets: tuple[str, ...]


@dataclass(frozen=True)
class IncidentView:
    state: str
    failure_class: str
    asset: str
    from_column: str
    to_column: str
    old_data_type: str
    new_data_type: str
    observed_at: str
    failure_messages: tuple[str, ...]
    hypothesis: str
    repair_allowed: str
    repair_applied: str
    repair_path: str
    repair_count: str
    original_sql: str
    repaired_sql: str
    replacements: tuple[str, ...]
    scope_flags: tuple[CheckView, ...]
    rules: tuple[CheckView, ...]
    revalidation_state: str
    revalidation: tuple[CheckView, ...]
    change_summary: str
    original_lines: tuple[SqlLineView, ...]
    repaired_lines: tuple[SqlLineView, ...]


@dataclass(frozen=True)
class PreviewView:
    state: str
    relation: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    note: str
    sampled_row_count: str = _UNAVAILABLE
    total_row_count: str = _UNAVAILABLE
    truncated: str = _UNAVAILABLE
    captured_rows: tuple[tuple[str, ...], ...] = ()

    @property
    def displayed_row_count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True)
class SqlFileView:
    path: str
    sql: str


@dataclass(frozen=True)
class QualityView:
    tests_state: str
    tests: tuple[CheckView, ...]
    tests_passed: str
    tests_total: str
    aggregate_test_flag: str
    quality_state: str
    quality_checks: tuple[CheckView, ...]
    all_quality_checks: tuple[CheckView, ...]
    quality_passed: str
    quality_row_count: str
    reconciliation_state: str
    reconciliation: tuple[CheckView, ...]

    @property
    def engine_reconciliation_count(self) -> int:
        return len(self.all_quality_checks) - len(self.quality_checks)

    @property
    def quality_count_note(self) -> str:
        if self.quality_state != _PRESENT:
            return "Quality Engine check results unavailable; missing checks are not a pass."
        return (
            f"{len(self.all_quality_checks)} Quality Engine "
            f"{_plural(len(self.all_quality_checks), 'check')} = "
            f"{len(self.quality_checks)} ordinary quality "
            f"{_plural(len(self.quality_checks), 'check')} + "
            f"{self.engine_reconciliation_count} reconciliation "
            f"{_plural(self.engine_reconciliation_count, 'check')} shown below."
        )

    @property
    def reconciliation_count_note(self) -> str:
        flags = len(self.reconciliation) - self.engine_reconciliation_count
        flag_count = f"{flags} additional persisted {_plural(flags, 'flag')}"
        if self.quality_state != _PRESENT:
            return (
                f"{flag_count}. Quality Engine reconciliation checks "
                "are unavailable. These flags are outside the Quality Engine check total."
            )
        return (
            f"{len(self.reconciliation)} reconciliation "
            f"{_plural(len(self.reconciliation), 'signal')} = "
            f"{self.engine_reconciliation_count} "
            f"{_plural(self.engine_reconciliation_count, 'check')} included in the "
            f"{len(self.all_quality_checks)} Quality Engine "
            f"{_plural(len(self.all_quality_checks), 'check')} + "
            f"{flag_count}. These flags are outside that check total."
        )


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else noun + "s"


@dataclass(frozen=True)
class VerificationView:
    state: str
    verdict: str
    checks: tuple[CheckView, ...]
    checks_passed: str
    checks_total: str
    reason_codes: tuple[str, ...]
    twin_snapshot_id: str
    estate_context_sha256: str


@dataclass(frozen=True)
class EvidenceView:
    state: str
    completeness_pct: str
    complete: str
    required_count: str
    present_count: str
    missing_sections: tuple[str, ...]
    digest_mismatches: tuple[str, ...]
    bundle_state: str
    bundle_sha256: str
    bundle_section_count: str


@dataclass(frozen=True)
class WorkflowView:
    workflow_id: str
    control_plane_state: str
    benchmark_outcome: str
    fail_reason: str
    block_reason: str
    duration: str
    phase_sequence: tuple[str, ...]
    timeline: tuple[StageView, ...]
    twin: TwinView
    incident: IncidentView
    models: tuple[SqlFileView, ...]
    model_count_note: str
    preview: PreviewView
    quality: QualityView
    verification: VerificationView
    evidence: EvidenceView
    governed_tool_operations: str
    policy_evaluations: str


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
    workflow_outcome: str
    determinism: str
    evidence_completeness: str
    evidence_complete: str
    summary: tuple[MetricView, ...]
    signals: tuple[SignalView, ...]
    what_happened: str
    workflows: tuple[WorkflowView, ...]
    audit_events: tuple[AuditEventView, ...]
    running_note: str

    @property
    def primary(self) -> WorkflowView | None:
        return self.workflows[0] if self.workflows else None

    @property
    def reruns(self) -> tuple[WorkflowView, ...]:
        return self.workflows[1:]


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    started_at: str
    finished_at: str
    workflow_count: int
    verifier_verdict: str = _UNAVAILABLE
    benchmark_verdict: str = _UNAVAILABLE
    models_generated: str = _UNAVAILABLE
    business_correctness: str = BUSINESS_CORRECTNESS


@dataclass(frozen=True)
class Dashboard:
    """Home page state derived from persisted run rows only."""

    runs: tuple[RunSummary, ...]
    latest: RunSummary | None
    latest_completed: RunSummary | None
    running: RunSummary | None

    @property
    def workflow_status(self) -> str:
        if self.running is not None:
            return "running"
        return self.latest.status if self.latest is not None else "no runs yet"


@dataclass(frozen=True)
class ExportFile:
    filename: str
    media_type: str
    body: bytes


def build_dashboard(runs: tuple[RunSummary, ...]) -> Dashboard:
    return Dashboard(
        runs=runs,
        latest=runs[0] if runs else None,
        latest_completed=next((item for item in runs if item.status == "completed"), None),
        running=next((item for item in runs if item.status == "running"), None),
    )


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
    evidence = _evidence(snapshot)
    panels = tuple(
        _workflow_panel(
            workflow_id,
            control_plane_state=control_plane_states.get(workflow_id, _UNAVAILABLE),
            artifact_bodies=artifacts.get(workflow_id, {}),
            snapshot=snapshot,
            snapshot_workflow=snapshot_workflows.get(workflow_id),
            evidence=evidence,
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
        workflow_outcome=_text(snapshot, "workflow_outcome"),
        determinism=_bool_text(snapshot, "determinism_equivalent"),
        evidence_completeness=_text(snapshot, "evidence_completeness_pct"),
        evidence_complete=_bool_text(snapshot, "evidence_complete"),
        summary=_summary(snapshot, panels[0] if panels else None),
        signals=_signals(status, panels[0] if panels else None),
        what_happened=_what_happened(
            status=status,
            snapshot=snapshot,
            primary=panels[0] if panels else None,
        ),
        workflows=panels,
        audit_events=audit_events,
        running_note=(
            "Running. The benchmark executes two workflows, one after the other. "
            "This page reads persisted status and audit events. It does not invent stages."
        ),
    )


def summarize_snapshot(body: dict[str, Any] | None) -> tuple[str, str, str]:
    """Verifier verdict, benchmark verdict, and model count for one history row."""
    if not isinstance(body, dict) or body.get("schema_version") not in READABLE_SNAPSHOT_VERSIONS:
        return _UNAVAILABLE, _UNAVAILABLE, _UNAVAILABLE
    workflows = body.get("workflows")
    first = workflows[0] if isinstance(workflows, list) and workflows else None
    verifier = _UNAVAILABLE
    if isinstance(first, dict) and first.get("verifier_verdict") in {"PASS", "FAIL"}:
        verifier = str(first["verifier_verdict"])
    metrics = body.get("metrics")
    models = _text(metrics if isinstance(metrics, dict) else None, "models_generated")
    return verifier, _text(body, "benchmark_verdict"), models


def export_file(page: RunPage, name: str) -> ExportFile | None:
    """Build one allowlisted export from the first workflow panel."""
    panel = page.primary
    if panel is None:
        return None
    if name == "output-preview":
        return _preview_csv(panel.preview)
    if name == "original-sql":
        return _text_file("original.sql", "text/plain; charset=utf-8", panel.incident.original_sql)
    if name == "repaired-sql":
        return _text_file("repaired.sql", "text/plain; charset=utf-8", panel.incident.repaired_sql)
    if name == "generated-sql":
        if not panel.models:
            return None
        chunks = [f"-- {item.path}\n{item.sql}" for item in panel.models]
        return _text_file("generated.sql", "text/plain; charset=utf-8", "\n\n".join(chunks))
    if name == "quality":
        return _checks_json(
            "quality.json", panel.quality.quality_state, panel.quality.all_quality_checks
        )
    if name == "verifier":
        if panel.verification.state != _PRESENT:
            return None
        return _checks_json("verifier.json", panel.verification.verdict, panel.verification.checks)
    if name == "tests":
        return _checks_json("tests.json", panel.quality.tests_state, panel.quality.tests)
    return None


def _workflow_panel(
    workflow_id: str,
    *,
    control_plane_state: str,
    artifact_bodies: dict[str, dict[str, Any]],
    snapshot: dict[str, Any] | None,
    snapshot_workflow: dict[str, Any] | None,
    evidence: EvidenceView,
) -> WorkflowView:
    snap = snapshot_workflow or {}
    twin = _twin(snapshot, artifact_bodies)
    incident = _incident(snap, artifact_bodies)
    models = _models(snap.get("models"))
    quality = _quality(snap, artifact_bodies)
    verification = _verification(artifact_bodies.get("verifier_verdict"))
    panel_evidence = _with_bundle(evidence, artifact_bodies.get("evidence_bundle"))
    phases = _string_list(snap, "phase_sequence")
    governed = _snap_text(snap, "governed_tool_operations")
    policies = _snap_text(snap, "policy_evaluations")
    return WorkflowView(
        workflow_id=workflow_id,
        control_plane_state=control_plane_state,
        benchmark_outcome=_snap_text(snap, "benchmark_outcome"),
        fail_reason=_snap_text(snap, "fail_reason"),
        block_reason=_snap_text(snap, "block_reason"),
        duration=_duration(snap.get("wall_clock_duration_ms")),
        phase_sequence=phases,
        timeline=_timeline(
            snapshot=snapshot,
            phases=phases,
            twin=twin,
            models=models,
            governed=governed,
            policies=policies,
            quality=quality,
            incident=incident,
            verification=verification,
            evidence=panel_evidence,
        ),
        twin=twin,
        incident=incident,
        models=models,
        model_count_note=_model_count_note(snapshot, models),
        preview=_preview(snap.get("output_preview")),
        quality=quality,
        verification=verification,
        evidence=panel_evidence,
        governed_tool_operations=governed,
        policy_evaluations=policies,
    )


def _summary(
    snapshot: dict[str, Any] | None, primary: WorkflowView | None
) -> tuple[MetricView, ...]:
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    body = metrics if isinstance(metrics, dict) else None
    verifier = primary.verification.verdict if primary is not None else _UNAVAILABLE
    same_population = "Same dispatch population as the other count."
    return (
        MetricView(
            "models",
            "Required MVP models",
            _text(body, "models_generated"),
            primary.model_count_note
            if primary is not None and primary.models
            else "Interview MVP benchmark count; generated SQL can include additional models.",
        ),
        MetricView("tests", "Tests", _text(body, "tests_executed"), "dbt tests executed"),
        MetricView(
            "quality",
            "Quality Engine checks",
            _text(body, "quality_checks_executed"),
            "Includes the reconciliation checks; additional persisted flags are separate.",
        ),
        MetricView(
            "incidents", "Incident", _text(body, "detected_incidents"), "incidents detected"
        ),
        MetricView(
            "repairs", "Repair", _text(body, "automatic_repairs"), "bounded repairs applied"
        ),
        MetricView(
            "human",
            "Human intervention",
            _text(body, "human_interventions"),
            "approvals during the run",
        ),
        MetricView(
            "evidence",
            "Evidence completeness",
            _percent(_text(body, "evidence_completeness_pct")),
            "required evidence sections present",
        ),
        MetricView(
            "governed",
            "Governed operations",
            _text(body, "governed_tool_operations"),
            same_population,
            "secondary",
        ),
        MetricView(
            "policy",
            "Policy evaluations",
            _text(body, "policy_evaluations"),
            same_population,
            "secondary",
        ),
        MetricView(
            "verifier",
            "Verifier verdict",
            verifier,
            "Evidence consistency only. Not business correctness.",
            "signal",
        ),
    )


def _timeline(
    *,
    snapshot: dict[str, Any] | None,
    phases: tuple[str, ...],
    twin: TwinView,
    models: tuple[SqlFileView, ...],
    governed: str,
    policies: str,
    quality: QualityView,
    incident: IncidentView,
    verification: VerificationView,
    evidence: EvidenceView,
) -> tuple[StageView, ...]:
    """Derive the engineering loop from persisted evidence. Missing evidence is unavailable."""
    seen = set(phases)
    executed = seen.intersection({"EXECUTION"})
    generation_detail = (
        f"{len(models)} dbt SQL files generated" if models else "Generation phase recorded"
    )
    if "DESIGN" in seen and generation_detail != _UNAVAILABLE:
        generation_detail = f"{generation_detail} after model design"
    stages = [
        _stage(
            "request",
            "Business objective",
            snapshot is not None,
            _text(snapshot, "business_objective") if snapshot is not None else _UNAVAILABLE,
            "#scenario",
        ),
        _stage(
            "estate",
            "Estate context",
            twin.state == _PRESENT or bool(seen.intersection({"DISCOVERY", "PROFILING"})),
            (
                f"{twin.pinned_asset_count} assets pinned in Digital Twin snapshot"
                if twin.state == _PRESENT
                else "Discovery and profiling phases recorded"
            ),
            "#estate",
        ),
        _stage(
            "generation",
            "Model generation",
            "GENERATION" in seen or "DESIGN" in seen or bool(models),
            generation_detail,
            "#preview",
        ),
        _stage(
            "execution",
            "Execution",
            bool(executed),
            (
                f"{governed} governed operations, the same population as "
                f"{policies} policy evaluations"
                if governed != _UNAVAILABLE and policies != _UNAVAILABLE
                else "Execution phase recorded"
            ),
            "#telemetry",
        ),
    ]
    tests_ok = quality.tests_state == _PRESENT
    stages.append(
        StageView(
            "testing",
            "Testing",
            _outcome_state(
                tests_ok, quality.tests_passed == quality.tests_total and quality.tests_total != "0"
            ),
            (
                f"{quality.tests_passed} of {quality.tests_total} dbt tests passed"
                if tests_ok
                else _UNAVAILABLE
            ),
            "#quality",
        )
    )
    drift_present = incident.state == _PRESENT
    stages.append(
        _stage(
            "incident",
            "Incident",
            drift_present,
            f"{incident.from_column} renamed to {incident.to_column} on {incident.asset}"
            if drift_present
            else _UNAVAILABLE,
            "#incident",
        )
    )
    stages.append(
        _stage(
            "diagnosis",
            "Diagnosis",
            incident.failure_class != _UNAVAILABLE,
            f"Failure class {incident.failure_class}"
            if incident.failure_class != _UNAVAILABLE
            else _UNAVAILABLE,
            "#incident",
        )
    )
    stages.append(
        StageView(
            "repair",
            "Bounded repair",
            _outcome_state(
                incident.repair_applied != _UNAVAILABLE, incident.repair_applied == "true"
            ),
            (
                f"{incident.repair_count} allowlisted column repair applied to "
                f"{incident.repair_path}"
                if incident.repair_applied == "true"
                else (
                    "Repair proposed but not applied"
                    if incident.repair_applied == "false"
                    else _UNAVAILABLE
                )
            ),
            "#incident",
        )
    )
    revalidated = incident.revalidation_state == _PRESENT
    stages.append(
        StageView(
            "revalidation",
            "Revalidation",
            _outcome_state(
                revalidated, all(item.outcome == "true" for item in incident.revalidation)
            ),
            (
                "Recompile, rerun, tests, and quality after the repair"
                if revalidated
                else _UNAVAILABLE
            ),
            "#incident",
        )
    )
    stages.append(
        StageView(
            "verification",
            "Verification",
            _outcome_state(verification.state == _PRESENT, verification.verdict == "PASS"),
            (
                f"Evidence consistency {verification.verdict} "
                f"({verification.checks_passed} of {verification.checks_total} checks)"
                if verification.state == _PRESENT
                else _UNAVAILABLE
            ),
            "#verification",
        )
    )
    stages.append(
        StageView(
            "evidence",
            "Evidence",
            _outcome_state(evidence.bundle_state == _PRESENT, evidence.complete == "true"),
            (
                f"{evidence.bundle_section_count} sealed sections · "
                f"{_percent(evidence.completeness_pct)} complete"
                if evidence.bundle_state == _PRESENT
                else _UNAVAILABLE
            ),
            "#evidence",
        )
    )
    return tuple(stages)


def _signals(status: str, primary: WorkflowView | None) -> tuple[SignalView, ...]:
    """Separate technical completion, evidence verification, and business correctness."""
    verdict = primary.verification.verdict if primary is not None else _UNAVAILABLE
    if verdict == "PASS":
        verification_detail = (
            "The verifier accepted the persisted evidence for this run, including the "
            "repair record. It does not independently rerun the warehouse and it does "
            "not establish financial correctness."
        )
    elif verdict == "FAIL":
        verification_detail = (
            "The verifier rejected the persisted evidence. "
            "This is not a business-correctness result."
        )
    else:
        verification_detail = "Verifier artifact unavailable. A missing verdict is not a pass."
    if status == "completed":
        technical_detail = "The workflow finished and stored its artifacts."
    elif status == "running":
        technical_detail = "The workflow is still executing. Stage results are not inferred."
    elif status == "failed":
        technical_detail = "The workflow did not finish successfully."
    else:
        technical_detail = "Run status from the persisted console row."
    return (
        SignalView("technical", "Technical workflow", status, technical_detail),
        SignalView("verification", "Evidence verification", verdict, verification_detail),
        SignalView(
            "business",
            "Business correctness",
            BUSINESS_CORRECTNESS,
            "Validated against the independent fixture oracle for the defined synthetic "
            "contract. This is not production financial validation.",
        ),
    )


def _what_happened(
    *,
    status: str,
    snapshot: dict[str, Any] | None,
    primary: WorkflowView | None,
) -> str:
    """One sentence from persisted values. Omit any claim the run did not store."""
    if status == "running" or snapshot is None:
        return ""
    metrics = snapshot.get("metrics")
    body = metrics if isinstance(metrics, dict) else None
    incident = primary.incident if primary is not None else None
    objective = _text(snapshot, "business_objective").lower()
    product = "the customer revenue data product" if "customer revenue" in objective else ""
    clauses: list[str] = []
    models = _count(_text(body, "models_generated"))
    if status == "completed" and models is not None and models > 0 and product:
        clauses.append(f"built {product}")
    elif models is not None and models > 0:
        clauses.append(f"generated {models} models")
    elif models == 0:
        clauses.append("recorded no generated models")

    incidents = _count(_text(body, "detected_incidents"))
    if (
        incidents == 1
        and incident is not None
        and incident.state == _PRESENT
        and incident.from_column != _UNAVAILABLE
        and incident.to_column != _UNAVAILABLE
    ):
        clauses.append(
            "detected one schema drift incident "
            f"({incident.from_column} renamed to {incident.to_column})"
        )
    elif incidents == 1:
        clauses.append("detected one incident")
    elif incidents == 0:
        clauses.append("detected no incident")
    elif incidents is not None:
        clauses.append(f"detected {incidents} incidents")

    repairs = _count(_text(body, "automatic_repairs"))
    applied = incident.repair_applied if incident is not None else _UNAVAILABLE
    if repairs == 1 and applied == "true":
        clauses.append("applied one bounded repair")
    elif applied == "false":
        clauses.append("did not apply the proposed repair")
    elif repairs == 0:
        clauses.append("applied no automatic repair")
    elif repairs is not None and repairs > 1:
        clauses.append(f"applied {repairs} automatic repairs")

    if incident is not None and incident.revalidation and incident.revalidation_state == _PRESENT:
        if all(item.outcome == "true" for item in incident.revalidation):
            clauses.append("reran validation")
        else:
            clauses.append("reran validation with a failed check")

    human = _count(_text(body, "human_interventions"))
    if status == "completed":
        ending = "completed the workflow"
        if human == 0:
            ending += " without human intervention"
        elif human is not None and human > 0:
            noun = "intervention" if human == 1 else "interventions"
            ending += f" with {human} human {noun}"
        clauses.append(ending)
    elif status == "failed":
        clauses.append("did not complete the workflow")

    if not clauses:
        return ""
    sentence = clauses[0] if len(clauses) == 1 else ", ".join(clauses[:-1]) + ", and " + clauses[-1]
    return f"Data Pilot AI {sentence}."


def _count(value: str) -> int | None:
    if value == _UNAVAILABLE:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _sql_line_diff(
    original: str, repaired: str
) -> tuple[tuple[SqlLineView, ...], tuple[SqlLineView, ...]]:
    if original == _UNAVAILABLE or repaired == _UNAVAILABLE:
        return (), ()
    import difflib

    before = original.splitlines() or [original]
    after = repaired.splitlines() or [repaired]
    before_changed: set[int] = set()
    after_changed: set[int] = set()
    matcher = difflib.SequenceMatcher(a=before, b=after)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_changed.update(range(i1, i2))
        after_changed.update(range(j1, j2))
    return (
        tuple(SqlLineView(text, index in before_changed) for index, text in enumerate(before)),
        tuple(SqlLineView(text, index in after_changed) for index, text in enumerate(after)),
    )


def _change_summary(original: str, repaired: str, replacements: tuple[str, ...]) -> str:
    if original == _UNAVAILABLE or repaired == _UNAVAILABLE:
        return ""
    if replacements:
        changed = ", ".join(replacements)
        return (
            f"The recorded SQL change is the column reference {changed}. "
            "Highlighted lines are the only lines that differ. "
            "This is one allowlisted column reference, not a general SQL rewrite."
        )
    if original == repaired:
        return "The stored original SQL and repaired SQL are identical."
    return "Highlighted lines are the only lines that differ between the stored SQL texts."


def _stage(key: str, title: str, present: bool, detail: str, href: str) -> StageView:
    return StageView(key, title, _COMPLETE if present else _UNAVAILABLE, detail, href)


def _outcome_state(present: bool, passed: bool) -> str:
    if not present:
        return _UNAVAILABLE
    return _COMPLETE if passed else _ISSUE


def _twin(snapshot: dict[str, Any] | None, bodies: dict[str, dict[str, Any]]) -> TwinView:
    """Digital Twin summary. Per-workflow artifacts win over the run-level snapshot copy."""
    summary = snapshot.get("digital_twin") if isinstance(snapshot, dict) else None
    body = summary if isinstance(summary, dict) else None
    snapshot_id = _text(bodies.get("twin_snapshot"), "twin_snapshot_id")
    estate_digest = _text(bodies.get("estate_context"), "sha256")
    if snapshot_id == _UNAVAILABLE:
        snapshot_id = _text(body, "snapshot_id")
    if estate_digest == _UNAVAILABLE:
        estate_digest = _text(body, "estate_context_sha256")
    if body is None and snapshot_id == _UNAVAILABLE and estate_digest == _UNAVAILABLE:
        return TwinView(_UNAVAILABLE, _UNAVAILABLE, _UNAVAILABLE, _UNAVAILABLE, _UNAVAILABLE, ())
    return TwinView(
        state=_PRESENT,
        snapshot_id=snapshot_id,
        manifest_sha256=_text(body, "manifest_sha256"),
        estate_context_sha256=estate_digest,
        pinned_asset_count=_text(body, "pinned_asset_count"),
        selected_assets=_string_list(body, "selected_assets"),
    )


def _incident(snap: dict[str, Any], bodies: dict[str, dict[str, Any]]) -> IncidentView:
    proposal = bodies.get("repair_proposal")
    validation = bodies.get("repair_validation")
    application = bodies.get("repair_application")
    revalidation = bodies.get("post_repair_validation")
    drift_body = _drift_observation(bodies.get("twin_observations"))
    proposal_body = proposal if isinstance(proposal, dict) else None
    source = drift_body or proposal_body
    present = source is not None
    failure_class = _short(proposal_body, "failure_class")
    if failure_class == _UNAVAILABLE:
        failure_class = _snap_text(snap, "repair_class")
    repair_count = _snap_text(snap, "repair_count")
    original_sql = _snap_text(snap, "original_sql")
    repaired_sql = _short(proposal_body, "patched_sql")
    replacements = _replacements(validation)
    original_lines, repaired_lines = _sql_line_diff(original_sql, repaired_sql)
    return IncidentView(
        state=_PRESENT if present else _UNAVAILABLE,
        failure_class=failure_class,
        asset=_asset_address(source),
        from_column=_short(source, "from_column"),
        to_column=_short(source, "to_column"),
        old_data_type=_short(drift_body, "old_data_type"),
        new_data_type=_short(drift_body, "new_data_type"),
        observed_at=_short(drift_body, "observed_at"),
        failure_messages=failure_messages(bodies.get("original_failure")),
        hypothesis=_short(proposal_body, "hypothesis"),
        repair_allowed=_flag(validation, "allowed"),
        repair_applied=_flag(application, "applied"),
        repair_path=_short(proposal_body, "artifact_path"),
        repair_count=repair_count,
        original_sql=original_sql,
        repaired_sql=repaired_sql,
        replacements=replacements,
        scope_flags=_scope_flags(validation),
        rules=_rules(validation),
        revalidation_state=_PRESENT if isinstance(revalidation, dict) else _UNAVAILABLE,
        revalidation=_revalidation(revalidation),
        change_summary=_change_summary(original_sql, repaired_sql, replacements),
        original_lines=original_lines,
        repaired_lines=repaired_lines,
    )


def _drift_observation(body: dict[str, Any] | None) -> dict[str, Any] | None:
    """The persisted DriftEvidence inside the twin_observations evidence section."""
    if not isinstance(body, dict):
        return None
    drift = body.get("drift")
    return drift if isinstance(drift, dict) and drift.get("drifted") is True else None


def _asset_address(body: dict[str, Any] | None) -> str:
    if not isinstance(body, dict):
        return _UNAVAILABLE
    asset = body.get("asset")
    if isinstance(asset, dict):
        address = asset.get("address")
        if isinstance(address, list) and address:
            return ".".join(str(part) for part in address)
    return _UNAVAILABLE


def _replacements(validation: dict[str, Any] | None) -> tuple[str, ...]:
    diff = _parsed_diff(validation)
    pairs = diff.get("column_reference_replacements") if diff else None
    if not isinstance(pairs, list):
        return ()
    found: list[str] = []
    for item in pairs:
        if isinstance(item, list) and len(item) == 2:
            found.append(f"{item[0]} → {item[1]}")
    return tuple(found)


_SCOPE_FLAG_LABELS: tuple[tuple[str, str], ...] = (
    ("join_changed", "Join changed"),
    ("filter_changed", "Filter changed"),
    ("grouping_changed", "Grouping changed"),
    ("grain_changed", "Grain changed"),
    ("materialization_changed", "Materialization changed"),
    ("macro_changed", "Macro changed"),
    ("yaml_changed", "YAML changed"),
    ("test_weakened", "Test weakened"),
    ("other_sql_changed", "Other SQL changed"),
    ("broader_than_allowed", "Broader than allowed"),
)


def _scope_flags(validation: dict[str, Any] | None) -> tuple[CheckView, ...]:
    """Parsed-diff scope checks. Outcome is true when the aspect stayed unchanged."""
    diff = _parsed_diff(validation)
    if diff is None:
        return ()
    rows: list[CheckView] = []
    for key, label in _SCOPE_FLAG_LABELS:
        if key not in diff:
            continue
        rows.append(CheckView(label, "true" if diff.get(key) is False else "false", key))
    return tuple(rows)


def _parsed_diff(validation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(validation, dict):
        return None
    diff = validation.get("parsed_diff")
    return diff if isinstance(diff, dict) else None


def _rules(validation: dict[str, Any] | None) -> tuple[CheckView, ...]:
    if not isinstance(validation, dict) or not isinstance(validation.get("rules"), list):
        return ()
    rows: list[CheckView] = []
    for item in validation["rules"]:
        if not isinstance(item, dict) or "passed" not in item:
            continue
        rows.append(
            CheckView(
                name=str(item.get("rule_id") or "rule"),
                outcome="true" if item.get("passed") is True else "false",
                detail=str(item.get("detail") or "")[:240],
            )
        )
    return tuple(rows)


def _revalidation(body: dict[str, Any] | None) -> tuple[CheckView, ...]:
    if not isinstance(body, dict):
        return ()
    labels = (
        ("execute_ok", "dbt rerun"),
        ("tests_ok", "dbt tests after repair"),
        ("quality_passed", "Quality checks after repair"),
    )
    return tuple(CheckView(label, _flag(body, key), key) for key, label in labels if key in body)


def _quality(snap: dict[str, Any], bodies: dict[str, dict[str, Any]]) -> QualityView:
    tests = _test_rows(snap.get("individual_tests"))
    quality = bodies.get("quality_results")
    quality_body = quality if isinstance(quality, dict) and "checks" in quality else None
    checks = _quality_rows(quality_body)
    passed_tests = sum(1 for item in tests if item.outcome == "pass")
    reconciliation = _reconciliation(checks, bodies)
    return QualityView(
        tests_state=_PRESENT if tests else _UNAVAILABLE,
        tests=tests,
        tests_passed=str(passed_tests) if tests else _UNAVAILABLE,
        tests_total=str(len(tests)) if tests else _UNAVAILABLE,
        aggregate_test_flag=_flag(bodies.get("dbt_tests"), "ok"),
        quality_state=_PRESENT if quality_body is not None else _UNAVAILABLE,
        quality_checks=tuple(item for item in checks if item.name not in _RECONCILIATION_CHECK_IDS),
        all_quality_checks=checks,
        quality_passed=_flag(quality_body, "passed"),
        quality_row_count=_text(quality_body, "row_count"),
        reconciliation_state=_PRESENT if reconciliation else _UNAVAILABLE,
        reconciliation=reconciliation,
    )


def _reconciliation(
    checks: tuple[CheckView, ...], bodies: dict[str, dict[str, Any]]
) -> tuple[CheckView, ...]:
    rows = [item for item in checks if item.name in _RECONCILIATION_CHECK_IDS]
    revenue = bodies.get("revenue_payment_reconciliation")
    if isinstance(revenue, dict) and "passed" in revenue:
        rows.append(
            CheckView(
                "revenue_payment_reconciliation",
                _flag(revenue, "passed"),
                "Supervisor revenue and payment reconciliation flag (evidence section)",
            )
        )
    gateway = bodies.get("reconciliation")
    if isinstance(gateway, dict) and "reconciled" in gateway:
        rows.append(
            CheckView(
                "gateway_dispatch_reconciled",
                _flag(gateway, "reconciled"),
                "All governed tool dispatches reconciled flag (evidence section)",
            )
        )
    return tuple(rows)


def _verification(body: dict[str, Any] | None) -> VerificationView:
    verdict = _verdict(body)
    if verdict is None or not isinstance(body, dict):
        return VerificationView(
            _UNAVAILABLE,
            _UNAVAILABLE,
            (),
            _UNAVAILABLE,
            _UNAVAILABLE,
            (),
            _UNAVAILABLE,
            _UNAVAILABLE,
        )
    checks = _verifier_rows(body)
    codes = body.get("reason_codes")
    return VerificationView(
        state=_PRESENT,
        verdict=verdict,
        checks=checks,
        checks_passed=str(sum(1 for item in checks if item.outcome == "true")),
        checks_total=str(len(checks)),
        reason_codes=tuple(str(item) for item in codes) if isinstance(codes, list) else (),
        twin_snapshot_id=_text(body, "twin_snapshot_id"),
        estate_context_sha256=_text(body, "estate_context_sha256"),
    )


def _evidence(snapshot: dict[str, Any] | None) -> EvidenceView:
    body = snapshot.get("evidence_completeness") if isinstance(snapshot, dict) else None
    detail = body if isinstance(body, dict) else None
    required = _string_list(detail, "required_sections")
    present = _string_list(detail, "present_sections")
    completeness = _text(detail, "completeness_pct")
    complete = _bool_text(detail, "complete")
    if detail is None and isinstance(snapshot, dict):
        completeness = _text(snapshot, "evidence_completeness_pct")
        complete = _bool_text(snapshot, "evidence_complete")
    return EvidenceView(
        state=_PRESENT if completeness != _UNAVAILABLE else _UNAVAILABLE,
        completeness_pct=completeness,
        complete=complete,
        required_count=str(len(required)) if detail is not None else _UNAVAILABLE,
        present_count=str(len(present)) if detail is not None else _UNAVAILABLE,
        missing_sections=_string_list(detail, "missing_sections"),
        digest_mismatches=_string_list(detail, "digest_mismatches"),
        bundle_state=_UNAVAILABLE,
        bundle_sha256=_UNAVAILABLE,
        bundle_section_count=_UNAVAILABLE,
    )


def _with_bundle(evidence: EvidenceView, bundle: dict[str, Any] | None) -> EvidenceView:
    if not isinstance(bundle, dict) or not isinstance(bundle.get("sections"), list):
        return evidence
    return EvidenceView(
        state=_PRESENT,
        completeness_pct=evidence.completeness_pct,
        complete=evidence.complete,
        required_count=evidence.required_count,
        present_count=evidence.present_count,
        missing_sections=evidence.missing_sections,
        digest_mismatches=evidence.digest_mismatches,
        bundle_state=_PRESENT,
        bundle_sha256=_text(bundle, "bundle_sha256"),
        bundle_section_count=str(len(bundle["sections"])),
    )


def _find_snapshot(
    artifacts: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    for bodies in artifacts.values():
        body = bodies.get(SNAPSHOT_ARTIFACT_TYPE)
        if isinstance(body, dict) and body.get("schema_version") in READABLE_SNAPSHOT_VERSIONS:
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


def _model_count_note(snapshot: dict[str, Any] | None, models: tuple[SqlFileView, ...]) -> str:
    metrics = snapshot.get("metrics") if isinstance(snapshot, dict) else None
    required = _text(metrics if isinstance(metrics, dict) else None, "models_generated")
    if not models:
        return "Generated SQL file count unavailable."
    benchmark = (
        f"The benchmark counts {required} required Interview MVP models. "
        if required != _UNAVAILABLE
        else "The required MVP benchmark count is unavailable. "
    )
    note = f"{benchmark}This workflow exposes {len(models)} generated SQL model files."
    if any(item.path == "models/marts/fct_invoices.sql" for item in models):
        note += " fct_invoices.sql is additional to the required MVP models."
    return note


def _preview(value: object) -> PreviewView:
    empty = PreviewView(_UNAVAILABLE, "", (), (), "output preview unavailable")
    if not isinstance(value, dict):
        return empty
    columns = value.get("columns")
    rows = value.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return empty
    names = tuple(str(item) for item in columns)
    captured = [row for row in rows if isinstance(row, dict)]
    selected = _representative_preview_rows(captured, names)
    rendered = tuple(tuple(_cell(row.get(name)) for name in names) for row in selected)
    note = value.get("note")
    selection_note = (
        "Deterministic display of stored executed rows, preferring nonzero invoice, payment "
        "and refund amounts where captured."
    )
    if not any(
        _nonzero_amount(row.get(name))
        for row in captured
        for name in _ACTIVITY_COLUMNS
        if name in names
    ):
        selection_note += (
            " No nonzero paid_amount, refunded_amount or net_paid_amount is available in "
            "the captured sample. Activity outside this sample is unknown."
        )
    return PreviewView(
        state=_PRESENT,
        relation=str(value.get("relation") or ""),
        columns=names,
        rows=rendered,
        note=f"{note} {selection_note}" if isinstance(note, str) and note else selection_note,
        sampled_row_count=_text(value, "sampled_row_count"),
        total_row_count=_text(value, "total_row_count"),
        truncated=_bool_text(value, "truncated"),
        captured_rows=tuple(tuple(_cell(row.get(name)) for name in names) for row in captured),
    )


def _representative_preview_rows(
    rows: list[dict[str, Any]], columns: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    """Select stored rows only, covering each captured amount before filling the bound.

    Ties follow persisted order; the selected rows retain that order. Never derive
    amounts or retrieve additional warehouse rows for a presentation sample.
    """
    activity = tuple(name for name in _ACTIVITY_COLUMNS if name in columns)
    amounts = activity + (("invoiced_amount",) if "invoiced_amount" in columns else ())
    selected: set[int] = set()
    for name in amounts:
        match = next((i for i, row in enumerate(rows) if _nonzero_amount(row.get(name))), None)
        if match is not None:
            selected.add(match)
    active = [i for i, row in enumerate(rows) if any(_nonzero_amount(row.get(n)) for n in activity)]
    for index in [*active, *range(len(rows))]:
        if len(selected) >= _MAX_PREVIEW_ROWS:
            break
        selected.add(index)
    return tuple(rows[index] for index in sorted(selected))


def _nonzero_amount(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return False
    return amount.is_finite() and amount != 0


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


def _string_list(body: dict[str, Any] | None, key: str) -> tuple[str, ...]:
    if not isinstance(body, dict):
        return ()
    value = body.get(key)
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _percent(value: str) -> str:
    return value if value == _UNAVAILABLE else f"{value}%"


def _duration(value: object) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return _UNAVAILABLE
    if value < 1000:
        return f"{value} ms"
    return f"{value / 1000:.1f} s"


def _cell(value: object) -> str:
    if value is None:
        return "null"
    return str(value)


def _preview_csv(preview: PreviewView) -> ExportFile | None:
    if preview.state != _PRESENT:
        return None
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(preview.columns)
    for row in preview.captured_rows:
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
