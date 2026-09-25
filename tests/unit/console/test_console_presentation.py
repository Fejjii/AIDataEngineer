"""Presenter behaviour for the polished console. Evidence in, unavailable out."""

from __future__ import annotations

from typing import Any

from aide.app.console.present import (
    RunSummary,
    build_dashboard,
    export_file,
    present_run,
    summarize_snapshot,
)
from aide.app.console.sources import group_source_catalog, load_source_catalog
from aide.persistence.console import EVIDENCE_ARTIFACT_TYPES, SNAPSHOT_ARTIFACT_TYPE

_WF = "11111111-1111-1111-1111-111111111111"
_SHA = "a" * 64


def _snapshot(version: int = 2, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": version,
        "business_objective": "Build a customer revenue analytical data product.",
        "benchmark_verdict": "PASS",
        "workflow_outcome": "VERIFIED",
        "determinism_equivalent": True,
        "evidence_completeness_pct": 100,
        "evidence_complete": True,
        "workflows": [
            {
                "workflow_id": _WF,
                "benchmark_outcome": "VERIFIED",
                "fail_reason": None,
                "block_reason": None,
                "models": [
                    {"path": "models/staging/stg_billing__invoices.sql", "sql": "select 1"},
                    {"path": "models/marts/mart_customer_revenue_daily.sql", "sql": "select 2"},
                ],
                "original_sql": "select INVOICE_STATUS from invoices",
                "individual_tests": [
                    {"test_name": "not_null_a", "model": "a", "column": "id", "status": "pass"},
                    {"test_name": "unique_b", "model": "b", "column": "id", "status": "pass"},
                ],
                "output_preview": {
                    "relation": "AIDE_DEV.mart_customer_revenue_daily",
                    "columns": ["customer_sk", "invoiced_amount"],
                    "rows": [{"customer_sk": 1, "invoiced_amount": 10.5}],
                    "sampled_row_count": 1,
                    "total_row_count": 11341,
                    "truncated": True,
                    "note": "Bounded sample.",
                },
            }
        ],
    }
    if version >= 2:
        body.update(
            {
                "metrics": {
                    "models_generated": 21,
                    "tests_executed": 23,
                    "quality_checks_executed": 25,
                    "governed_tool_operations": 36,
                    "policy_evaluations": 36,
                    "detected_incidents": 1,
                    "automatic_repairs": 1,
                    "human_interventions": 0,
                    "evidence_completeness_pct": 100,
                },
                "evidence_completeness": {
                    "required_sections": ["request", "plan", "verifier_verdict"],
                    "present_sections": ["request", "plan", "verifier_verdict"],
                    "missing_sections": [],
                    "digest_mismatches": [],
                    "completeness_pct": 100,
                    "complete": True,
                },
                "digital_twin": {
                    "snapshot_id": "cf847f9d-090e-4dac-9b3b-afe0c9bd1a8c",
                    "manifest_sha256": _SHA,
                    "estate_context_sha256": _SHA,
                    "pinned_asset_count": 102,
                    "selected_assets": ["VANTARA_RAW.BILLING.INVOICES"],
                },
            }
        )
        body["workflows"][0].update(
            {
                "phase_sequence": [
                    "RECEIVED",
                    "PLANNING",
                    "DISCOVERY",
                    "PROFILING",
                    "DESIGN",
                    "GENERATION",
                    "POLICY_CHECK",
                    "EXECUTION",
                    "VALIDATION",
                    "REPAIR",
                    "EXECUTION",
                    "VALIDATION",
                ],
                "repair_class": "SCHEMA_MISMATCH",
                "repair_count": 1,
                "verifier_verdict": "PASS",
                "governed_tool_operations": 36,
                "policy_evaluations": 36,
                "wall_clock_duration_ms": 6012,
            }
        )
    body.update(overrides)
    return body


def _artifacts(verdict: str = "PASS") -> dict[str, dict[str, Any]]:
    return {
        SNAPSHOT_ARTIFACT_TYPE: _snapshot(),
        "repair_proposal": {
            "failure_class": "SCHEMA_MISMATCH",
            "asset": {"address": ["VANTARA_RAW", "BILLING", "INVOICES"]},
            "from_column": "INVOICE_STATUS",
            "to_column": "STATUS",
            "artifact_path": "models/staging/stg_billing__invoices.sql",
            "patched_sql": "select STATUS from invoices",
            "hypothesis": "source column renamed",
        },
        "repair_validation": {
            "allowed": True,
            "parsed_diff": {
                "column_reference_replacements": [["INVOICE_STATUS", "STATUS"]],
                "join_changed": False,
                "test_weakened": False,
                "broader_than_allowed": False,
            },
            "rules": [{"rule_id": "single_column", "passed": True, "detail": "ok"}],
        },
        "repair_application": {"applied": True},
        "original_failure": {
            "results": [{"status": "error", "model": "stg", "message": "Binder Error"}]
        },
        "twin_observations": {
            "drift": {
                "drifted": True,
                "asset": {"address": ["VANTARA_RAW", "BILLING", "INVOICES"]},
                "from_column": "INVOICE_STATUS",
                "to_column": "STATUS",
                "old_data_type": "VARCHAR",
                "new_data_type": "VARCHAR",
                "observed_at": "2026-09-24T16:00:00",
            }
        },
        "twin_snapshot": {"twin_snapshot_id": "per-workflow-snapshot"},
        "estate_context": {"sha256": _SHA},
        "post_repair_validation": {"tests_ok": True, "quality_passed": True, "execute_ok": True},
        "quality_results": {
            "passed": True,
            "row_count": 11341,
            "checks": [
                {"check_id": "mart_non_empty", "passed": True, "detail": "rows=11341"},
                {"check_id": "payment_sum_matches_mart", "passed": True, "detail": "ok"},
            ],
        },
        "revenue_payment_reconciliation": {"passed": True},
        "reconciliation": {"reconciled": True},
        "dbt_tests": {"ok": True},
        "verifier_verdict": {
            "verdict": verdict,
            "checks": [
                {"check_id": "snapshot_identity", "passed": True, "detail": "ok"},
                {"check_id": "reconciled", "passed": verdict == "PASS", "detail": "gateway"},
            ],
            "reason_codes": [] if verdict == "PASS" else ["UNRECONCILED"],
            "twin_snapshot_id": "cf847f9d-090e-4dac-9b3b-afe0c9bd1a8c",
            "estate_context_sha256": _SHA,
        },
        "evidence_bundle": {"bundle_sha256": _SHA, "sections": [{"name": "request"}] * 29},
    }


def _page(artifacts: dict[str, dict[str, Any]]) -> Any:
    return present_run(
        run_id="22222222-2222-2222-2222-222222222222",
        status="completed",
        error_message=None,
        started_at="2026-09-24 16:00:00 UTC",
        finished_at="2026-09-24 16:00:12 UTC",
        workflow_ids=(_WF,),
        control_plane_states={_WF: "VALIDATION"},
        artifacts={_WF: artifacts},
        audit_events=(),
    )


def test_complete_evidence_populates_every_stage_from_persisted_values() -> None:
    page = _page(_artifacts())
    panel = page.workflows[0]
    assert [stage.key for stage in panel.timeline] == [
        "request",
        "estate",
        "generation",
        "execution",
        "testing",
        "incident",
        "diagnosis",
        "repair",
        "revalidation",
        "verification",
        "evidence",
    ]
    assert [stage.title for stage in panel.timeline] == [
        "Business objective",
        "Estate context",
        "Model generation",
        "Execution",
        "Testing",
        "Incident",
        "Diagnosis",
        "Bounded repair",
        "Revalidation",
        "Verification",
        "Evidence",
    ]
    assert {stage.state for stage in panel.timeline} == {"complete"}
    metrics = {metric.key: metric.value for metric in page.summary}
    assert metrics["models"] == "21"
    assert metrics["incidents"] == "1"
    assert metrics["repairs"] == "1"
    assert metrics["human"] == "0"
    assert metrics["evidence"] == "100%"
    assert metrics["verifier"] == "PASS"
    assert page.business_correctness == "NOT_VALIDATED"
    assert panel.duration == "6.0 s"


def test_narrative_uses_persisted_counts_and_omits_missing_claims() -> None:
    page = _page(_artifacts())
    assert page.what_happened == (
        "Data Pilot AI built the customer revenue data product, "
        "detected one schema drift incident (INVOICE_STATUS renamed to STATUS), "
        "applied one bounded repair, reran validation, "
        "and completed the workflow without human intervention."
    )
    groups = {metric.key: metric.group for metric in page.summary}
    assert groups["models"] == "primary"
    assert groups["governed"] == "secondary"
    assert groups["policy"] == "secondary"
    assert groups["verifier"] == "signal"
    assert [signal.key for signal in page.signals] == ["technical", "verification", "business"]
    assert page.signals[0].value == "completed"
    assert page.signals[1].value == "PASS"
    assert page.signals[2].value == "NOT_VALIDATED"
    changed = [line.text for line in page.workflows[0].incident.original_lines if line.changed]
    assert changed == ["select INVOICE_STATUS from invoices"]
    assert "INVOICE_STATUS → STATUS" in page.workflows[0].incident.change_summary

    sparse = _page({SNAPSHOT_ARTIFACT_TYPE: _snapshot(version=1)})
    assert "without human intervention" not in sparse.what_happened
    assert "bounded repair" not in sparse.what_happened
    assert "schema drift" not in sparse.what_happened
    assert sparse.signals[1].value == "unavailable"


def test_incident_view_reads_drift_repair_and_revalidation_evidence() -> None:
    incident = _page(_artifacts()).workflows[0].incident
    assert incident.state == "present"
    assert incident.failure_class == "SCHEMA_MISMATCH"
    assert incident.asset == "VANTARA_RAW.BILLING.INVOICES"
    assert (incident.from_column, incident.to_column) == ("INVOICE_STATUS", "STATUS")
    assert incident.old_data_type == "VARCHAR"
    assert incident.replacements == ("INVOICE_STATUS → STATUS",)
    assert incident.repair_allowed == "true"
    assert incident.repair_applied == "true"
    assert incident.original_sql == "select INVOICE_STATUS from invoices"
    assert incident.repaired_sql == "select STATUS from invoices"
    # Scope flags read as "unchanged" checks: a false diff flag is a passing outcome.
    assert {flag.outcome for flag in incident.scope_flags} == {"true"}
    assert incident.revalidation_state == "present"
    assert [row.outcome for row in incident.revalidation] == ["true", "true", "true"]


def test_quality_signals_stay_separate() -> None:
    quality = _page(_artifacts()).workflows[0].quality
    assert (quality.tests_passed, quality.tests_total) == ("2", "2")
    assert quality.aggregate_test_flag == "true"
    assert [check.name for check in quality.quality_checks] == ["mart_non_empty"]
    assert [check.name for check in quality.reconciliation] == [
        "payment_sum_matches_mart",
        "revenue_payment_reconciliation",
        "gateway_dispatch_reconciled",
    ]
    assert len(quality.all_quality_checks) == 2


def test_verifier_fail_is_an_issue_not_a_pass() -> None:
    page = _page(_artifacts(verdict="FAIL"))
    panel = page.workflows[0]
    assert panel.verification.verdict == "FAIL"
    assert panel.verification.reason_codes == ("UNRECONCILED",)
    assert panel.verification.checks_passed == "1"
    stage = {stage.key: stage for stage in panel.timeline}["verification"]
    assert stage.state == "issue"
    assert "FAIL" in stage.detail
    assert page.business_correctness == "NOT_VALIDATED"


def test_twin_prefers_per_workflow_artifacts_over_snapshot_copy() -> None:
    twin = _page(_artifacts()).workflows[0].twin
    assert twin.state == "present"
    assert twin.snapshot_id == "per-workflow-snapshot"
    assert twin.estate_context_sha256 == _SHA
    assert twin.pinned_asset_count == "102"
    assert twin.selected_assets == ("VANTARA_RAW.BILLING.INVOICES",)


def test_evidence_view_combines_completeness_and_bundle() -> None:
    evidence = _page(_artifacts()).workflows[0].evidence
    assert evidence.completeness_pct == "100"
    assert evidence.complete == "true"
    assert (evidence.required_count, evidence.present_count) == ("3", "3")
    assert evidence.bundle_state == "present"
    assert evidence.bundle_section_count == "29"
    assert evidence.bundle_sha256 == _SHA


def test_version_one_snapshot_remains_readable_with_new_fields_unavailable() -> None:
    artifacts = {SNAPSHOT_ARTIFACT_TYPE: _snapshot(version=1)}
    page = _page(artifacts)
    panel = page.workflows[0]
    assert page.benchmark_verdict == "PASS"
    assert panel.models[0].path == "models/staging/stg_billing__invoices.sql"
    assert panel.preview.total_row_count == "11341"
    assert panel.twin.state == "unavailable"
    assert panel.phase_sequence == ()
    assert {metric.value for metric in page.summary} == {"unavailable"}
    states = {stage.key: stage.state for stage in panel.timeline}
    assert states["generation"] == "complete"
    assert states["testing"] == "complete"
    assert states["incident"] == "unavailable"
    assert states["verification"] == "unavailable"


def test_unknown_snapshot_version_is_ignored() -> None:
    page = _page({SNAPSHOT_ARTIFACT_TYPE: _snapshot(version=99)})
    assert page.benchmark_verdict == "unavailable"
    assert page.workflows[0].models == ()


def test_exports_use_incident_and_quality_views() -> None:
    page = _page(_artifacts())
    original = export_file(page, "original-sql")
    repaired = export_file(page, "repaired-sql")
    quality = export_file(page, "quality")
    assert original is not None and b"INVOICE_STATUS" in original.body
    assert repaired is not None and b"STATUS" in repaired.body
    assert quality is not None and b"payment_sum_matches_mart" in quality.body
    assert export_file(page, "not-a-real-export") is None


def test_summarize_snapshot_reads_metrics_not_file_counts() -> None:
    assert summarize_snapshot(_snapshot()) == ("PASS", "PASS", "21")
    assert summarize_snapshot(_snapshot(version=1)) == ("unavailable", "PASS", "unavailable")
    assert summarize_snapshot(None) == ("unavailable", "unavailable", "unavailable")


def test_dashboard_prefers_running_then_latest_status() -> None:
    running = RunSummary("r1", "running", "now", "", 0)
    completed = RunSummary("r2", "completed", "earlier", "earlier", 2, verifier_verdict="PASS")
    failed = RunSummary("r3", "failed", "before", "before", 0)
    board = build_dashboard((running, completed, failed))
    assert board.workflow_status == "running"
    assert board.running is running
    assert board.latest_completed is completed
    assert build_dashboard((failed,)).workflow_status == "failed"
    assert build_dashboard(()).workflow_status == "no runs yet"
    assert build_dashboard(()).latest_completed is None


def test_source_catalog_groups_by_schema_and_marks_masked_columns() -> None:
    catalog = group_source_catalog(load_source_catalog())
    assert [group.label for group in catalog.groups] == ["CRM", "Billing", "Payments", "Product"]
    assert catalog.table_count == 10
    assert catalog.database == "VANTARA_RAW"
    contacts = next(table for table in catalog.tables if table.name == "CONTACTS")
    assert contacts.schema == "CRM"
    assert "EMAIL" in contacts.masked_columns
    assert sum(len(group.tables) for group in catalog.groups) == catalog.table_count


def test_console_allowlist_only_names_persisted_evidence_types() -> None:
    assert "schema_drift" not in EVIDENCE_ARTIFACT_TYPES
    assert {"twin_observations", "evidence_bundle", "post_repair_validation"} <= (
        EVIDENCE_ARTIFACT_TYPES
    )
