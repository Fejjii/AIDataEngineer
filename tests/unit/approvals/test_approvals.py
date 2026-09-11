from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from tests.helpers import approval_record, policy_request, principal

from aide.approvals.matching import (
    match_operation_approval,
    simultaneous_subjects_approved,
)
from aide.approvals.routing import route_approval_rejection
from aide.domain.approvals import (
    ApprovalStatus,
    BudgetIncreaseApproval,
    DesignApproval,
    OperationApproval,
)
from aide.domain.costs import BudgetScope, CostUnit
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.states import WorkflowState
from aide.policy.engine import PolicyEngine, collect_approval_requirements


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
