from __future__ import annotations

from collections.abc import Sequence

from hypothesis import given, settings
from hypothesis import strategies as st
from tests.helpers import SNOWFLAKE_DEV, SNOWFLAKE_RO, mock_provenance, policy_request, read_sql

from aide.domain.permissions import PermissionLevel
from aide.policy.engine import DENY_RULES, PolicyEngine, rule_r1, rule_r4b, rule_r9, rule_r20
from aide.policy.reasons import DenyClass, ReasonCode


def _engine(order: Sequence[tuple[str, object]] | None = None) -> PolicyEngine:
    return PolicyEngine(order)  # type: ignore[arg-type]


def test_all_denial_reasons_preserved_and_security_dominates() -> None:
    request = policy_request(
        capability_id="execute_query",
        connector=SNOWFLAKE_DEV,
        grants=frozenset(),
        sql=read_sql(
            parse_ok=True,
            read_only=False,
            destructive=True,
            multi=True,
            dynamic=True,
            unsafe=("UNSAFE_FUNCTION:SYSTEM$ABORT", "DYNAMIC_SQL"),
            unknown=("WeirdNode",),
            stages=("@RAW.STAGE",),
        ),
        extra={"capability_known": False, "connector_advertises_capability": False},
    )
    decision = _engine().evaluate(request)
    assert decision.decision == "DENY"
    assert ReasonCode.UNKNOWN_TARGET in decision.reasons
    assert ReasonCode.PERM_NOT_GRANTED in decision.reasons
    assert ReasonCode.PERMISSION_NOT_ALLOWED_FOR_CONNECTOR in decision.reasons
    assert ReasonCode.READ_ONLY_IDENTITY_REQUIRED in decision.reasons
    assert ReasonCode.SQL_DESTRUCTIVE in decision.reasons
    assert ReasonCode.SQL_MULTI in decision.reasons
    assert ReasonCode.SQL_SECURITY in decision.reasons
    assert decision.deny_class == DenyClass.SECURITY.value
    assert decision.routing == "FAIL_CLOSED"
    assert decision.approval_requirements == ()


def test_scope_dominates_environmental() -> None:
    request = policy_request(
        capability_id="execute_query",
        connector=SNOWFLAKE_DEV,
        grants=frozenset({PermissionLevel.READ}),
        extra={"connector_registered": False},
        sql=read_sql(),
    )
    decision = _engine().evaluate(request)
    assert ReasonCode.UNKNOWN_TARGET in decision.reasons
    assert decision.deny_class == DenyClass.SCOPE.value
    assert decision.routing == "FAIL_CLOSED"


@given(st.permutations(list(range(len(DENY_RULES)))))
@settings(max_examples=50, deadline=None)
def test_policy_result_invariant_to_rule_ordering(indices: list[int]) -> None:
    order = tuple(DENY_RULES[index] for index in indices)
    request = policy_request(
        capability_id="execute_query",
        connector=SNOWFLAKE_DEV,
        grants=frozenset(),
        sql=read_sql(destructive=True, read_only=False, multi=True, unsafe=("DYNAMIC_SQL",)),
        extra={"capability_known": False},
    )
    baseline = PolicyEngine().evaluate(request)
    shuffled = PolicyEngine(order).evaluate(request)
    assert shuffled.decision == baseline.decision
    assert shuffled.reasons == baseline.reasons
    assert shuffled.deny_class == baseline.deny_class
    assert shuffled.routing == baseline.routing
    assert shuffled.approval_requirements == baseline.approval_requirements


def test_approvals_not_evaluated_when_denial_exists() -> None:
    request = policy_request(
        capability_id="deploy_staging",
        connector=None,
        grants=frozenset(),
        extra={"capability_known": False, "connector_registered": False},
    )
    decision = _engine().evaluate(request)
    assert decision.decision == "DENY"
    assert decision.approval_requirements == ()


def test_read_requires_read_only_identity_and_snowflake_dev_cannot_satisfy() -> None:
    assert PermissionLevel.READ not in SNOWFLAKE_DEV.allowed_permissions
    assert SNOWFLAKE_RO.identity_class.value == "READ_ONLY"
    denied = _engine().evaluate(
        policy_request(capability_id="execute_query", connector=SNOWFLAKE_DEV)
    )
    assert ReasonCode.READ_ONLY_IDENTITY_REQUIRED in denied.reasons
    assert ReasonCode.PERMISSION_NOT_ALLOWED_FOR_CONNECTOR in denied.reasons
    allowed = _engine().evaluate(
        policy_request(
            capability_id="execute_query",
            connector=SNOWFLAKE_RO,
            grants=frozenset({PermissionLevel.READ}),
        )
    )
    assert allowed.decision == "ALLOW"
    assert allowed.routing == "EXECUTE"


def test_mock_provenance_cannot_enter_real_delivery() -> None:
    from aide.connectors.base.spec import (
        CapabilityImplementation,
        ConnectorKind,
        ConnectorSpec,
        IdentityClass,
        ObjectAllowList,
    )
    from aide.domain.enums import TargetEnv

    github = ConnectorSpec(
        connector_id="github",
        kind=ConnectorKind.VCS,
        vendor="github",
        version="1.0.0",
        target_environment=TargetEnv.DEV,
        identity_class=IdentityClass.VCS,
        implementations=frozenset(
            {
                CapabilityImplementation(
                    capability_id="prepare_git_change",
                    supported_contract_versions=frozenset({1}),
                    input_schema_versions=frozenset({1}),
                    output_schema_versions=frozenset({1}),
                )
            }
        ),
        allowed_permissions=frozenset({PermissionLevel.GIT_WRITE}),
        allow_list=ObjectAllowList(repos=frozenset({"org/repo"})),
        is_fake=False,
    )
    decision = _engine().evaluate(
        policy_request(
            capability_id="prepare_git_change",
            connector=github,
            grants=frozenset({PermissionLevel.GIT_WRITE}),
            provenance=(mock_provenance(),),
            sql=None,
        )
    )
    assert ReasonCode.MOCK_PROVENANCE_TO_REAL_TARGET in decision.reasons
    assert decision.decision == "DENY"


def test_deny_rule_helpers_are_pure() -> None:
    request = policy_request(connector=SNOWFLAKE_DEV)
    assert rule_r4b(request)
    assert rule_r1(policy_request(extra={"capability_known": False}))
    assert rule_r9(policy_request(sql=read_sql(unsafe=("UNSAFE_FUNCTION:FOO",), stages=("@x",))))
    assert rule_r20(
        policy_request(
            capability_id="prepare_git_change",
            connector=None,
            provenance=(mock_provenance(),),
            extra={"connector_registered": True, "connector_advertises_capability": True},
        )
    )
