from __future__ import annotations

from tests.helpers import policy_request, read_sql

from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.domain.sql import SqlText
from aide.policy.engine import PolicyEngine
from aide.policy.reasons import ReasonCode
from aide.policy.sql.classifier import classify_sql


def test_safe_sql_rejects_destructive_statements() -> None:
    result = classify_sql(SqlText(dialect="snowflake", text="DROP TABLE RAW.SALES.ORDERS"))
    assert result.is_read_only is False
    assert result.is_destructive is True
    decision = PolicyEngine().evaluate(
        policy_request(sql=result, capability_id="execute_query", connector=SNOWFLAKE_RO)
    )
    assert (
        ReasonCode.SQL_DESTRUCTIVE in decision.reasons
        or ReasonCode.READ_ONLY_REQUIRED in decision.reasons
    )
    assert decision.decision == "DENY"


def test_safe_sql_rejects_scope_violations() -> None:
    sql = classify_sql(SqlText(dialect="snowflake", text="SELECT 1 FROM OTHER.SECRET.TABLE"))
    decision = PolicyEngine().evaluate(
        policy_request(sql=sql, capability_id="execute_query", connector=SNOWFLAKE_RO)
    )
    assert ReasonCode.SCOPE_VIOLATION in decision.reasons
    assert decision.routing == "FAIL_CLOSED"


def test_read_execution_binds_snowflake_ro() -> None:
    decision = PolicyEngine().evaluate(
        policy_request(
            capability_id="execute_query",
            connector=SNOWFLAKE_RO,
            sql=read_sql(),
        )
    )
    assert decision.decision == "ALLOW"
    assert SNOWFLAKE_RO.identity_class.value == "READ_ONLY"


def test_snowflake_dev_is_rejected_for_read_path() -> None:
    decision = PolicyEngine().evaluate(
        policy_request(
            capability_id="execute_query",
            connector=SNOWFLAKE_DEV,
            sql=read_sql(),
            advertises=False,
        )
    )
    assert decision.decision == "DENY"
    assert ReasonCode.READ_ONLY_IDENTITY_REQUIRED in decision.reasons or (
        ReasonCode.PERMISSION_NOT_ALLOWED_FOR_CONNECTOR in decision.reasons
    )


def test_kernel_includes_slice_reasoning_capabilities() -> None:
    registry = kernel_registry()
    assert registry.contains("interpret_requirement", 1)
    assert registry.contains("generate_sql_query", 1)
    assert registry.contains("plan_phase", 1)
