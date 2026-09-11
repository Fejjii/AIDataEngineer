from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from tests.helpers import approval_record, policy_request, principal

from aide.approvals.matching import (
    match_budget_approval,
    match_design_approval,
    match_operation_approval,
    simultaneous_subjects_approved,
)
from aide.approvals.routing import route_approval_rejection
from aide.domain.approvals import (
    ApprovalRecord,
    ApprovalStatus,
    BudgetIncreaseApproval,
    DesignApproval,
    OperationApproval,
)
from aide.domain.costs import BudgetScope, CostEstimate, CostUnit
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState
from aide.policy.engine import PolicyEngine, collect_approval_requirements, granted
from aide.policy.request import PolicyRequest


def _now() -> datetime:
    return datetime.now(UTC)


def _operation(**overrides: object) -> OperationApproval:
    payload = dict(
        operation_idempotency_key="a" * 64,
        resolved_input_digest="b" * 64,
        artifact_hashes=("c" * 64,),
        capability_id="deploy_staging",
        capability_contract_version=1,
        connector_id="dbt_staging",
        connector_version="1.0.0",
        target_environment=TargetEnv.STAGING,
        required_permission=PermissionLevel.STAGING_DEPLOY,
        external_state_digest="d" * 64,
        expires_at=_now() + timedelta(hours=1),
    )
    payload.update(overrides)
    return OperationApproval.model_validate(payload)


def test_full_binding_must_match() -> None:
    now = _now()
    subject = _operation()
    actor = principal()
    record = approval_record(subject, actor, now=now)
    assert match_operation_approval(record, subject.as_binding(), now=now)
    mutated = subject.as_binding().model_copy(update={"artifact_hashes": ("e" * 64,)})
    assert not match_operation_approval(record, mutated, now=now)
    expired = record.model_copy(update={"expires_at": now - timedelta(seconds=1)})
    assert not match_operation_approval(expired, subject.as_binding(), now=now)


def test_simultaneous_approval_aggregation() -> None:
    now = _now()
    request = policy_request(
        capability_id="deploy_staging",
        connector=None,
        grants=frozenset(),
        extra={
            "design_approval_required": True,
            "design_subject": DesignApproval(
                design_artifact_hash="des1",
                validation_report_hash="val1",
                invariant_hashes=("inv1",),
                expires_at=now + timedelta(hours=1),
            ),
            "estimated_cost": __import__(
                "aide.domain.costs", fromlist=["CostEstimate"]
            ).CostEstimate(
                scope=BudgetScope.WORKFLOW_LLM,
                unit=CostUnit.USD,
                worst_case=Decimal("20"),
                current_cap=Decimal("5"),
                ledger_version=3,
                prior_cap=Decimal("5"),
            ),
        },
    )
    required = collect_approval_requirements(request)
    kinds = {item.kind for item in required}
    assert "OPERATION" in kinds
    assert "DESIGN" in kinds
    assert "BUDGET_INCREASE" in kinds
    actor = request.principal
    records = tuple(approval_record(item, actor, now=now) for item in required)
    assert simultaneous_subjects_approved(
        records,
        required,
        now=now,
        operation_binding=next(
            item.as_binding() for item in required if isinstance(item, OperationApproval)
        ),
    )
    assert not simultaneous_subjects_approved(records[1:], required, now=now)


def test_approval_rejection_routes() -> None:
    design = route_approval_rejection(
        DesignApproval(
            design_artifact_hash="d",
            validation_report_hash="v",
            invariant_hashes=(),
            expires_at=_now(),
        )
    )
    assert design.workflow_state is WorkflowState.PLANNING

    staging_ok = route_approval_rejection(_operation(), documented_pr_fallback=True)
    assert staging_ok.workflow_state is WorkflowState.COMPLETED

    staging_block = route_approval_rejection(_operation(), documented_pr_fallback=False)
    assert staging_block.workflow_state is WorkflowState.BLOCKED

    destructive = route_approval_rejection(
        _operation(
            capability_id="drop_dataset",
            required_permission=PermissionLevel.DESTRUCTIVE,
            target_environment=TargetEnv.DEV,
        ),
        required_operation=True,
    )
    assert destructive.workflow_state is WorkflowState.FAILED

    optional = route_approval_rejection(
        _operation(
            capability_id="prepare_git_change",
            required_permission=PermissionLevel.GIT_WRITE,
            target_environment=TargetEnv.DEV,
        ),
        required_operation=False,
    )
    assert optional.task_disposition.value == "SKIPPED(APPROVAL_REJECTED)"

    budget = route_approval_rejection(
        BudgetIncreaseApproval(
            budget_scope=BudgetScope.WORKFLOW_LLM,
            ledger_version=1,
            unit=CostUnit.USD,
            prior_cap=Decimal("1"),
            authorized_new_cap=Decimal("2"),
            authorized_delta=Decimal("1"),
            expires_at=_now(),
        )
    )
    assert budget.workflow_state is WorkflowState.BLOCKED


def test_policy_aggregates_approvals_only_without_denial() -> None:
    now = _now()
    request = policy_request(
        capability_id="deploy_staging",
        connector=None,
        grants=frozenset({PermissionLevel.STAGING_DEPLOY}),
        extra={
            "connector_registered": False,
            "estimated_cost": __import__(
                "aide.domain.costs", fromlist=["CostEstimate"]
            ).CostEstimate(
                scope=BudgetScope.WORKFLOW_LLM,
                unit=CostUnit.USD,
                worst_case=Decimal("20"),
                current_cap=Decimal("1"),
                ledger_version=1,
                prior_cap=Decimal("1"),
            ),
        },
    )
    denied = PolicyEngine().evaluate(request)
    assert denied.decision == "DENY"
    assert denied.approval_requirements == ()

    allowed_path = policy_request(
        capability_id="deploy_staging",
        connector=None,
        grants=frozenset(),
        extra={"connector_registered": True, "capability_known": True},
    )
    # deploy_staging requires a connector; without one R1 denies. Use a matching spec.
    from aide.connectors.base.spec import (
        CapabilityImplementation,
        ConnectorKind,
        ConnectorSpec,
        IdentityClass,
        ObjectAllowList,
    )

    dbt_staging = ConnectorSpec(
        connector_id="dbt_staging",
        kind=ConnectorKind.TRANSFORMATION,
        vendor="dbt",
        version="1.0.0",
        target_environment=TargetEnv.STAGING,
        identity_class=IdentityClass.STAGING_DEPLOY,
        implementations=frozenset(
            {
                CapabilityImplementation(
                    capability_id="deploy_staging",
                    supported_contract_versions=frozenset({1}),
                    input_schema_versions=frozenset({1}),
                    output_schema_versions=frozenset({1}),
                )
            }
        ),
        allowed_permissions=frozenset({PermissionLevel.STAGING_DEPLOY}),
        allow_list=ObjectAllowList(),
    )
    pending = PolicyEngine().evaluate(
        policy_request(
            capability_id="deploy_staging",
            connector=dbt_staging,
            grants=frozenset(),
            extra={"target_environment": TargetEnv.STAGING},
        )
    )
    assert pending.decision == "REQUIRE_APPROVAL"
    assert pending.routing == "APPROVAL"
    assert any(isinstance(item, OperationApproval) for item in pending.approval_requirements)
    del now
    del allowed_path
    _ = ApprovalStatus
    _ = uuid4


FIXED_NOW = datetime(2026, 9, 11, 16, 0, 0, tzinfo=UTC)
VALID_UNTIL = FIXED_NOW + timedelta(hours=1)
EXPIRED_AT = FIXED_NOW - timedelta(seconds=1)


def _design(**overrides: object) -> DesignApproval:
    payload: dict[str, object] = {
        "design_artifact_hash": "des1",
        "validation_report_hash": "val1",
        "invariant_hashes": ("inv1",),
        "expires_at": VALID_UNTIL,
    }
    payload.update(overrides)
    return DesignApproval.model_validate(payload)


def _budget(**overrides: object) -> BudgetIncreaseApproval:
    payload: dict[str, object] = {
        "budget_scope": BudgetScope.WORKFLOW_LLM,
        "ledger_version": 1,
        "unit": CostUnit.USD,
        "prior_cap": Decimal("1"),
        "authorized_new_cap": Decimal("2"),
        "authorized_delta": Decimal("1"),
        "expires_at": VALID_UNTIL,
    }
    payload.update(overrides)
    return BudgetIncreaseApproval.model_validate(payload)


def _record_for(
    subject: OperationApproval | DesignApproval | BudgetIncreaseApproval, *, expires_at: datetime
) -> ApprovalRecord:
    return approval_record(subject, principal(), now=FIXED_NOW).model_copy(
        update={"expires_at": expires_at}
    )


@pytest.mark.parametrize(
    ("record_expiry", "subject_expiry", "expected"),
    [
        (EXPIRED_AT, VALID_UNTIL, False),
        (VALID_UNTIL, EXPIRED_AT, False),
        (EXPIRED_AT, EXPIRED_AT, False),
        (VALID_UNTIL, VALID_UNTIL, True),
    ],
)
def test_expired_approvals_never_authorize_operation(
    record_expiry: datetime, subject_expiry: datetime, expected: bool
) -> None:
    subject = _operation(expires_at=subject_expiry)
    record = _record_for(subject, expires_at=record_expiry)
    assert match_operation_approval(record, subject.as_binding(), now=FIXED_NOW) is expected


@pytest.mark.parametrize(
    ("record_expiry", "subject_expiry", "expected"),
    [
        (EXPIRED_AT, VALID_UNTIL, False),
        (VALID_UNTIL, EXPIRED_AT, False),
        (EXPIRED_AT, EXPIRED_AT, False),
        (VALID_UNTIL, VALID_UNTIL, True),
    ],
)
def test_expired_approvals_never_authorize_design(
    record_expiry: datetime, subject_expiry: datetime, expected: bool
) -> None:
    subject = _design(expires_at=subject_expiry)
    record = _record_for(subject, expires_at=record_expiry)
    assert match_design_approval(record, _design(), now=FIXED_NOW) is expected


@pytest.mark.parametrize(
    ("record_expiry", "subject_expiry", "expected"),
    [
        (EXPIRED_AT, VALID_UNTIL, False),
        (VALID_UNTIL, EXPIRED_AT, False),
        (EXPIRED_AT, EXPIRED_AT, False),
        (VALID_UNTIL, VALID_UNTIL, True),
    ],
)
def test_expired_approvals_never_authorize_budget(
    record_expiry: datetime, subject_expiry: datetime, expected: bool
) -> None:
    subject = _budget(expires_at=subject_expiry)
    record = _record_for(subject, expires_at=record_expiry)
    assert match_budget_approval(record, _budget(), now=FIXED_NOW) is expected


def _grant_request(subject: OperationApproval) -> PolicyRequest:
    return policy_request(
        capability_id="prepare_git_change",
        connector=None,
        grants=frozenset(),
        now=FIXED_NOW,
        extra={
            "artifact_hashes": subject.artifact_hashes,
            "external_state_digest": subject.external_state_digest,
            "operation_idempotency_key": subject.operation_idempotency_key,
            "resolved_input_digest": subject.resolved_input_digest,
            "approvals": (_record_for(subject, expires_at=VALID_UNTIL),),
        },
    )


def test_expired_operation_approval_does_not_grant_permission() -> None:
    probe = policy_request(
        capability_id="prepare_git_change",
        connector=None,
        grants=frozenset(),
        now=FIXED_NOW,
    )
    live_subject = _operation(
        operation_idempotency_key=probe.operation_idempotency_key,
        resolved_input_digest=probe.resolved_input_digest,
        capability_id=probe.capability.id,
        capability_contract_version=probe.capability.version,
        connector_id="unbound",
        connector_version="unbound",
        target_environment=TargetEnv.DEV,
        required_permission=probe.capability.required_permission,
        expires_at=VALID_UNTIL,
    )
    expired_subject = live_subject.model_copy(update={"expires_at": EXPIRED_AT})
    assert granted(_grant_request(live_subject)) is True
    assert granted(_grant_request(expired_subject)) is False


def test_generated_approval_expiry_is_after_evaluated_at() -> None:
    request = policy_request(
        capability_id="deploy_staging",
        connector=None,
        grants=frozenset(),
        now=FIXED_NOW,
        extra={
            "target_environment": TargetEnv.STAGING,
            "approval_expires_at": VALID_UNTIL,
            "estimated_cost": CostEstimate(
                scope=BudgetScope.WORKFLOW_LLM,
                unit=CostUnit.USD,
                worst_case=Decimal("20"),
                current_cap=Decimal("5"),
                ledger_version=3,
                prior_cap=Decimal("5"),
            ),
        },
    )
    required = collect_approval_requirements(request)
    operations = [item for item in required if isinstance(item, OperationApproval)]
    budgets = [item for item in required if isinstance(item, BudgetIncreaseApproval)]
    assert operations
    assert budgets
    generated: list[OperationApproval | BudgetIncreaseApproval] = [*operations, *budgets]
    for subject in generated:
        assert subject.expires_at > request.evaluated_at
        assert subject.expires_at == VALID_UNTIL


def test_approval_expires_at_must_follow_evaluated_at() -> None:
    with pytest.raises(ValidationError, match="approval_expires_at"):
        policy_request(
            now=FIXED_NOW,
            extra={"approval_expires_at": FIXED_NOW},
        )
    with pytest.raises(ValidationError, match="approval_expires_at"):
        policy_request(
            now=FIXED_NOW,
            extra={"approval_expires_at": EXPIRED_AT},
        )


def test_generated_operation_binding_uses_authoritative_hashes() -> None:
    artifact_hashes = ("aa" * 32,)
    external_state = "ee" * 32
    request = policy_request(
        capability_id="deploy_staging",
        connector=None,
        grants=frozenset(),
        now=FIXED_NOW,
        extra={
            "target_environment": TargetEnv.STAGING,
            "artifact_hashes": artifact_hashes,
            "external_state_digest": external_state,
        },
    )
    generated = next(
        item
        for item in collect_approval_requirements(request)
        if isinstance(item, OperationApproval)
    )
    assert generated.artifact_hashes == artifact_hashes
    assert generated.artifact_hashes != (request.resolved_input_digest,)
    assert generated.external_state_digest == external_state
    assert generated.resolved_input_digest == request.resolved_input_digest


@pytest.mark.parametrize(
    "field",
    [
        "artifact_hashes",
        "external_state_digest",
        "resolved_input_digest",
        "connector_version",
        "required_permission",
    ],
)
def test_operation_approval_invalidated_by_binding_field(field: str) -> None:
    subject = _operation(expires_at=VALID_UNTIL)
    record = _record_for(subject, expires_at=VALID_UNTIL)
    binding = subject.as_binding()
    assert match_operation_approval(record, binding, now=FIXED_NOW)
    mutated_values: dict[str, object] = {
        "artifact_hashes": ("ff" * 32,),
        "external_state_digest": "gg" * 32,
        "resolved_input_digest": "hh" * 32,
        "connector_version": "9.9.9",
        "required_permission": PermissionLevel.DESTRUCTIVE,
    }
    mutated = binding.model_copy(update={field: mutated_values[field]})
    assert not match_operation_approval(record, mutated, now=FIXED_NOW)


def test_operation_approval_invalidated_by_expiry() -> None:
    subject = _operation(expires_at=VALID_UNTIL)
    record = _record_for(subject, expires_at=VALID_UNTIL)
    assert match_operation_approval(record, subject.as_binding(), now=FIXED_NOW)
    assert not match_operation_approval(
        record.model_copy(update={"expires_at": EXPIRED_AT}),
        subject.as_binding(),
        now=FIXED_NOW,
    )
    assert not match_operation_approval(
        _record_for(_operation(expires_at=EXPIRED_AT), expires_at=VALID_UNTIL),
        subject.as_binding().model_copy(update={}),
        now=FIXED_NOW,
    )
