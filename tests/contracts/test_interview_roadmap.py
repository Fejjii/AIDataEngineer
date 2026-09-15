from __future__ import annotations

from pathlib import Path

from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.domain.enums import TargetEnv
from aide.domain.roadmap import ACTIVE_INTERVIEW_TASKS, DEFERRED_AFTER_MVP004

ROOT = Path(__file__).resolve().parents[2]


def test_at22_docs_keep_only_mvp001_to_mvp004_active() -> None:
    tasks = (ROOT / ".ai" / "TASKS.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    boundary = (ROOT / "docs" / "pivot" / "PIVOT001_CONTRACT_BOUNDARY.md").read_text(
        encoding="utf-8"
    )
    for task_id in ACTIVE_INTERVIEW_TASKS:
        assert task_id in tasks
        assert task_id in plan
        assert task_id in boundary
    assert "MVP001 → MVP002 → MVP003 → MVP004" in plan or "MVP001 Digital Twin" in plan
    for deferred in DEFERRED_AFTER_MVP004:
        assert deferred in tasks
    assert "MVP005" not in ACTIVE_INTERVIEW_TASKS


def test_at18_offline_allow_lists_forbid_dev_raw_and_production() -> None:
    assert SNOWFLAKE_DEV.target_environment is TargetEnv.DEV
    assert SNOWFLAKE_RO.target_environment is TargetEnv.DEV
    assert "VANTARA_RAW" not in SNOWFLAKE_DEV.allow_list.databases
    assert "VANTARA_RAW" in SNOWFLAKE_RO.allow_list.databases
    assert "AIDE_DEV" in SNOWFLAKE_DEV.allow_list.databases
    assert "PRODUCTION" not in SNOWFLAKE_DEV.allow_list.databases
    assert "STAGING" not in SNOWFLAKE_DEV.allow_list.databases
    assert not SNOWFLAKE_DEV.advertises("execute_query")
    assert SNOWFLAKE_RO.advertises("execute_query", 1)
