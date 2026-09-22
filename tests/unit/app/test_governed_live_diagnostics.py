"""Governed live smoke reports the workflow failure before missing connectors."""

from __future__ import annotations

from aide.app.interview import governed_live_detail


def _detail(
    *,
    missing_connectors: set[str] | None = None,
    policy_ok: bool = True,
    production_or_staging: bool = False,
    evidence_ok: bool = True,
    workflow_failed: bool = False,
    fail_reason: str | None = None,
    block_reason: str | None = None,
    park_reason: str | None = None,
    execute_ok: bool = True,
    tests_ok: bool = True,
    quality_ok: bool = True,
) -> str:
    return governed_live_detail(
        missing_connectors=set() if missing_connectors is None else missing_connectors,
        policy_ok=policy_ok,
        production_or_staging=production_or_staging,
        evidence_ok=evidence_ok,
        workflow_failed=workflow_failed,
        fail_reason=fail_reason,
        block_reason=block_reason,
        park_reason=park_reason,
        execute_ok=execute_ok,
        tests_ok=tests_ok,
        quality_ok=quality_ok,
    )


def test_resource_limit_is_reported_before_missing_connectors() -> None:
    detail = _detail(
        workflow_failed=True,
        fail_reason="RESOURCE_LIMIT",
        missing_connectors={"dbt_dev", "snowflake_dev"},
        execute_ok=False,
        tests_ok=False,
        quality_ok=False,
        evidence_ok=False,
    )
    assert detail.startswith("RESOURCE_LIMIT")
    assert "gateway did not dispatch required connectors:" in detail
    assert detail.index("RESOURCE_LIMIT") < detail.index("gateway did not dispatch")
    assert "dbt_dev" in detail
    assert "snowflake_dev" in detail


def test_missing_connectors_remain_when_the_workflow_did_not_fail() -> None:
    detail = _detail(missing_connectors={"dbt_dev"})
    assert detail == "gateway did not dispatch required connectors: ['dbt_dev']"
    assert "RESOURCE_LIMIT" not in detail


def test_successful_live_detail_is_unchanged() -> None:
    detail = _detail()
    assert detail.startswith("governed Supervisor/Tool Gateway path")
    assert "VANTARA_RAW" in detail
