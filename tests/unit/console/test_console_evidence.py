from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aide.app.benchmarking.runner import build_fingerprint
from aide.app.console.present import present_run
from aide.app.console.snapshot import _model_files, public_failure_message
from aide.app.console.sources import load_source_catalog
from aide.app.supervisor import InterviewResult
from aide.capabilities.io import GenerateTransformationOutput, TransformationFile
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role


def _result() -> InterviewResult:
    principal = PrincipalRef(
        principal_id=uuid4(),
        authentication_source="LOCAL_SESSION",
        roles=frozenset({Role.OPERATOR}),
        session_id=uuid4(),
    )
    grants = GrantAuthorization(
        principal=principal,
        requested=frozenset({PermissionLevel.READ}),
        effective=frozenset({PermissionLevel.READ}),
        environment_policy_version="test",
        decided_at=datetime.now(UTC).replace(tzinfo=None),
    )
    return InterviewResult(workflow_id=uuid4(), principal=principal, grants=grants)


def test_model_files_reject_paths_outside_the_allowlist() -> None:
    result = _result()
    result.generated = GenerateTransformationOutput(
        files=(
            TransformationFile(path="models/staging/stg_billing__invoices.sql", content="select 1"),
            TransformationFile(path="../secrets.sql", content="select secret"),
            TransformationFile(path="models/schema.yml", content="version: 2", kind="SCHEMA_YML"),
        ),
        model_names=("stg_billing__invoices",),
        content_sha256="a" * 64,
    )
    files = _model_files(result)
    assert [item["path"] for item in files] == ["models/staging/stg_billing__invoices.sql"]


def test_output_preview_is_not_part_of_the_benchmark_fingerprint() -> None:
    result = _result()
    before = build_fingerprint(result)
    result.extra["output_preview"] = {
        "relation": "AIDE_DEV.mart_customer_revenue_daily",
        "rows": [],
    }
    assert build_fingerprint(result) == before


def test_missing_artifacts_are_unavailable_and_not_pass() -> None:
    workflow_id = "11111111-1111-1111-1111-111111111111"
    page = present_run(
        run_id="22222222-2222-2222-2222-222222222222",
        status="completed",
        error_message="<script>alert(1)</script>",
        started_at="2026-09-23 00:00:00 UTC",
        finished_at="2026-09-23 00:01:00 UTC",
        workflow_ids=(workflow_id,),
        control_plane_states={},
        artifacts={},
        audit_events=(),
    )
    panel = page.workflows[0]
    assert page.benchmark_verdict == "unavailable"
    assert panel.verification.verdict == "unavailable"
    assert panel.verification.state == "unavailable"
    assert panel.quality.quality_state == "unavailable"
    assert panel.quality.tests_state == "unavailable"
    assert panel.quality.reconciliation_state == "unavailable"
    assert panel.preview.state == "unavailable"
    assert panel.incident.state == "unavailable"
    assert panel.incident.original_sql == "unavailable"
    assert panel.incident.repaired_sql == "unavailable"
    assert panel.incident.repair_applied == "unavailable"
    assert panel.twin.state == "unavailable"
    assert panel.evidence.bundle_state == "unavailable"
    assert {stage.state for stage in panel.timeline} == {"unavailable"}
    assert {metric.value for metric in page.summary} == {"unavailable"}
    assert page.business_correctness == "VALIDATED_SYNTHETIC_CONTRACT"
    assert "<script>" in page.error_message


def test_failure_message_drops_secret_like_text() -> None:
    assert public_failure_message(RuntimeError("password=hunter2")) == "RuntimeError"
    assert "boom" in public_failure_message(RuntimeError("boom"))


def test_source_samples_are_capped_and_masked() -> None:
    tables = {item.address: item for item in load_source_catalog()}
    contacts = tables["VANTARA_RAW.CRM.CONTACTS"]
    assert len(contacts.sample_rows) == 5
    assert len(contacts.sample_columns) <= 8
    flat = " ".join(" ".join(row) for row in contacts.sample_rows)
    assert "taylor.johnson7213@novasystems-0.com" not in flat
    assert "@" in flat
    assert "***" in flat
    accounts = tables["VANTARA_RAW.CRM.ACCOUNTS"]
    assert "Nova Systems" not in " ".join(" ".join(row) for row in accounts.sample_rows)


def test_preview_samples_only_the_fixed_mart(tmp_path: object) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    connector = FakeDbtConnector(work_root=root)
    connector._conn.execute('CREATE SCHEMA IF NOT EXISTS "AIDE_DEV"')
    connector._conn.execute(
        'CREATE TABLE "AIDE_DEV"."mart_customer_revenue_daily" AS '
        "SELECT i AS invoiced_amount FROM range(21) t(i)"
    )
    preview = connector.capture_bounded_preview()
    assert preview is not None
    assert preview["relation"] == "AIDE_DEV.mart_customer_revenue_daily"
    assert preview["sampled_row_count"] == 20
    assert preview["truncated"] is True
    assert preview["total_row_count"] == 21
    connector._conn.execute('DROP TABLE "AIDE_DEV"."mart_customer_revenue_daily"')
    assert connector.capture_bounded_preview() is None
