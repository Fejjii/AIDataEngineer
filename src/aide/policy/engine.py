"""Deterministic policy engine. Evaluates every applicable denial."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from aide.domain.approvals import (
    ApprovalRecord,
    ApprovalStatus,
    ApprovalSubject,
    BudgetIncreaseApproval,
    DesignApproval,
    OperationApproval,
    OperationBinding,
    approval_is_effective,
)
from aide.domain.artifacts import transitive_mock_derived
from aide.domain.enums import ApprovalRule, TargetEnv
from aide.domain.git import GitChangeClassification
from aide.domain.permissions import PermissionLevel
from aide.domain.sql import SqlClassification
from aide.policy.reasons import (
    Decision,
    ReasonCode,
    deny_class_for_reasons,
    routing_for,
    sort_reasons,
)
from aide.policy.request import PolicyDecision, PolicyRequest

DenyRule = Callable[[PolicyRequest], frozenset[ReasonCode]]
RuleId = str

REAL_DELIVERY_CAPABILITIES = frozenset(
    {
        "prepare_git_change",
        "prepare_pull_request",
        "deploy_staging",
        "deploy_production",
    }
)
REAL_DELIVERY_PERMISSIONS = frozenset(
    {
        PermissionLevel.GIT_WRITE,
        PermissionLevel.STAGING_DEPLOY,
        PermissionLevel.PRODUCTION_WRITE,
    }
)


def granted(request: PolicyRequest) -> bool:
    required = request.capability.required_permission
    if required in request.workflow_grants:
        return True
    binding = _operation_binding(request)
    return any(
        approval_is_effective(record, request.evaluated_at)
        and isinstance(record.subject, OperationApproval)
        and record.subject.covers_operation(binding)
        for record in request.approvals
    )


def connector_allows(request: PolicyRequest) -> bool:
    if request.connector is None:
        return True
    return request.capability.required_permission in request.connector.allowed_permissions


def approval_eligible(request: PolicyRequest) -> bool:
    permission = request.capability.required_permission
    if permission is PermissionLevel.STAGING_DEPLOY:
        return True
    return permission is PermissionLevel.DESTRUCTIVE and request.target_environment is TargetEnv.DEV


def _operation_binding(request: PolicyRequest) -> OperationBinding:
    connector_id = request.connector.connector_id if request.connector else "unbound"
    connector_version = request.connector.version if request.connector else "unbound"
    target = request.target_environment or TargetEnv.DEV
    return OperationBinding(
        operation_idempotency_key=request.operation_idempotency_key,
        resolved_input_digest=request.resolved_input_digest,
        artifact_hashes=request.artifact_hashes,
        capability_id=request.capability.id,
        capability_contract_version=request.capability.version,
        connector_id=connector_id,
        connector_version=connector_version,
        target_environment=target,
        required_permission=request.capability.required_permission,
        external_state_digest=request.external_state_digest,
    )


def _sql(request: PolicyRequest) -> SqlClassification | None:
    payload = request.payload_classification
    return payload if isinstance(payload, SqlClassification) else None


def _git(request: PolicyRequest) -> GitChangeClassification | None:
    payload = request.payload_classification
    return payload if isinstance(payload, GitChangeClassification) else None


def rule_r1(request: PolicyRequest) -> frozenset[ReasonCode]:
    needs_connector = request.capability.connector_requirement.required
    if not request.capability_known:
        return frozenset({ReasonCode.UNKNOWN_TARGET})
    if needs_connector and (request.connector is None or not request.connector_registered):
        return frozenset({ReasonCode.UNKNOWN_TARGET})
    if needs_connector and not request.connector_advertises_capability:
        return frozenset({ReasonCode.UNKNOWN_TARGET})
    return frozenset()


def rule_r2(request: PolicyRequest) -> frozenset[ReasonCode]:
    if not request.capability.connector_requirement.required:
        return frozenset()
    health = request.connector_health
    if health is None or health.is_expired(request.evaluated_at):
        return frozenset({ReasonCode.CONNECTOR_UNAVAILABLE})
    if health.status not in {"AVAILABLE", "DEGRADED", "MOCK"}:
        return frozenset({ReasonCode.CONNECTOR_UNAVAILABLE})
    return frozenset()


def rule_r2b(request: PolicyRequest) -> frozenset[ReasonCode]:
    health = request.connector_health
    if health is None or health.status != "DEGRADED":
        return frozenset()
    reasons: set[ReasonCode] = set()
    if request.capability.required_permission in health.missing_permissions:
        reasons.add(ReasonCode.CONNECTOR_PERMISSION_MISSING)
    if any(code.startswith("SECRET_UNRESOLVED") for code in health.reason_codes):
        reasons.add(ReasonCode.SECRET_UNRESOLVED)
    return frozenset(reasons)


def rule_r3_deny(request: PolicyRequest) -> frozenset[ReasonCode]:
    if granted(request) or approval_eligible(request):
        return frozenset()
    return frozenset({ReasonCode.PERM_NOT_GRANTED})


def rule_r4(request: PolicyRequest) -> frozenset[ReasonCode]:
    if connector_allows(request):
        return frozenset()
    return frozenset({ReasonCode.PERMISSION_NOT_ALLOWED_FOR_CONNECTOR})


def rule_r4b(request: PolicyRequest) -> frozenset[ReasonCode]:
    if request.capability.required_permission is not PermissionLevel.READ:
        return frozenset()
    connector = request.connector
    if connector is None:
        return frozenset()
    if connector.kind.value not in {"warehouse", "database"}:
        return frozenset()
    if connector.identity_class.value != "READ_ONLY":
        return frozenset({ReasonCode.READ_ONLY_IDENTITY_REQUIRED})
    return frozenset()


def rule_r5(request: PolicyRequest) -> frozenset[ReasonCode]:
    if request.connector is None or request.target_environment is None:
        return frozenset()
    if request.target_environment is not request.connector.target_environment:
        return frozenset({ReasonCode.ENV_MISMATCH})
    return frozenset()


def rule_r6(request: PolicyRequest) -> frozenset[ReasonCode]:
    if request.target_environment is TargetEnv.PROD:
        return frozenset({ReasonCode.PROD_DISABLED_V1})
    return frozenset()


def rule_r7(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if sql is None:
        return frozenset()
    if not sql.parse_ok:
        return frozenset({ReasonCode.SQL_UNPARSEABLE})
    return frozenset()


def rule_r8(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if sql is None or not sql.parse_ok:
        return frozenset()
    if sql.is_destructive and request.capability.id != "drop_dataset":
        return frozenset({ReasonCode.SQL_DESTRUCTIVE})
    return frozenset()


def rule_r9(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if sql is None or not sql.parse_ok:
        return frozenset()
    reasons: set[ReasonCode] = set()
    if sql.has_dynamic_sql or sql.unknown_ast_nodes:
        reasons.add(ReasonCode.SQL_SECURITY)
    if any(
        name.startswith("UNSAFE:") or True for name in sql.functions if name not in sql.functions
    ):
        pass
    if sql.stages_or_urls:
        reasons.add(ReasonCode.SQL_SECURITY)
    if sql.unsafe_constructs:
        reasons.add(ReasonCode.SQL_UNSAFE_CONSTRUCT)
        if any("FUNCTION" in item or "UDF" in item for item in sql.unsafe_constructs):
            reasons.add(ReasonCode.SQL_UNSAFE_FUNCTION)
    if any("UNSAFE_FUNCTION" in item for item in sql.unsafe_constructs):
        reasons.add(ReasonCode.SQL_UNSAFE_FUNCTION)
    return frozenset(reasons)


def rule_r10(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if sql is None or not sql.parse_ok:
        return frozenset()
    if sql.is_multi_statement:
        return frozenset({ReasonCode.SQL_MULTI})
    return frozenset()


def rule_r11(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if sql is None or request.connector is None:
        return frozenset()
    allow = request.connector.allow_list
    for asset in (*sql.objects_read, *sql.objects_written):
        if not allow.contains_asset(asset):
            return frozenset({ReasonCode.SCOPE_VIOLATION})
    return frozenset()


def rule_r12(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if sql is None or not sql.objects_written:
        return frozenset()
    if not request.dev_namespace_schemas:
        return frozenset()
    for asset in sql.objects_written:
        if len(asset.address) < 2:
            return frozenset({ReasonCode.WRITE_OUTSIDE_NAMESPACE})
        if (asset.address[0], asset.address[1]) not in request.dev_namespace_schemas:
            return frozenset({ReasonCode.WRITE_OUTSIDE_NAMESPACE})
    return frozenset()


def rule_r13(request: PolicyRequest) -> frozenset[ReasonCode]:
    sql = _sql(request)
    if request.capability.id != "execute_query" or sql is None:
        return frozenset()
    if not sql.is_read_only:
        return frozenset({ReasonCode.READ_ONLY_REQUIRED})
    return frozenset()


def rule_r13b(request: PolicyRequest) -> frozenset[ReasonCode]:
    if request.capability.id != "drop_dataset":
        return frozenset()
    if request.drop_target_created_by_workflow is False:
        return frozenset({ReasonCode.PROVENANCE_MISMATCH})
    return frozenset()


def rule_r14(request: PolicyRequest) -> frozenset[ReasonCode]:
    git = _git(request)
    if git is None:
        return frozenset()
    protected = git.protected_branches
    if git.force or git.base_branch in protected or git.target_branch in protected:
        return frozenset({ReasonCode.PROTECTED_BRANCH})
    return frozenset()


def rule_r15(request: PolicyRequest) -> frozenset[ReasonCode]:
    git = _git(request)
    if git is None:
        return frozenset()
    if git.secret_scan_hit:
        return frozenset({ReasonCode.SECRET_IN_DIFF})
    return frozenset()


def rule_r20(request: PolicyRequest) -> frozenset[ReasonCode]:
    if not transitive_mock_derived(request.artifact_provenance):
        return frozenset()
    real_target = (
        request.capability.id in REAL_DELIVERY_CAPABILITIES
        or request.capability.required_permission in REAL_DELIVERY_PERMISSIONS
    )
    if not real_target:
        return frozenset()
    if request.connector is not None and request.connector.is_fake:
        return frozenset()
    return frozenset({ReasonCode.MOCK_PROVENANCE_TO_REAL_TARGET})


DENY_RULES: tuple[tuple[RuleId, DenyRule], ...] = (
    ("R1", rule_r1),
    ("R2", rule_r2),
    ("R2b", rule_r2b),
    ("R3", rule_r3_deny),
    ("R4", rule_r4),
    ("R4b", rule_r4b),
    ("R5", rule_r5),
    ("R6", rule_r6),
    ("R7", rule_r7),
    ("R8", rule_r8),
    ("R9", rule_r9),
    ("R10", rule_r10),
    ("R11", rule_r11),
    ("R12", rule_r12),
    ("R13", rule_r13),
    ("R13b", rule_r13b),
    ("R14", rule_r14),
    ("R15", rule_r15),
    ("R20", rule_r20),
)


def _has_matching_operation_approval(request: PolicyRequest) -> bool:
    binding = _operation_binding(request)
    return any(
        approval_is_effective(record, request.evaluated_at)
        and isinstance(record.subject, OperationApproval)
        and record.subject.covers_operation(binding)
        for record in request.approvals
    )


def _matching_records(request: PolicyRequest) -> tuple[ApprovalRecord, ...]:
    return tuple(
        record
        for record in request.approvals
        if approval_is_effective(record, request.evaluated_at)
    )


def collect_approval_requirements(request: PolicyRequest) -> tuple[ApprovalSubject, ...]:
    requirements: list[ApprovalSubject] = []
    if not granted(request) and approval_eligible(request):
        requirements.append(_synthetic_operation_approval(request))
    if request.capability.approval is ApprovalRule.ALWAYS and not _has_matching_operation_approval(
        request
    ):
        subject = _synthetic_operation_approval(request)
        if subject not in requirements:
            requirements.append(subject)
    if request.create_dataset_replace_unowned and request.capability.id == "create_dataset":
        subject = _synthetic_operation_approval(request, PermissionLevel.DESTRUCTIVE)
        if subject not in requirements:
            requirements.append(subject)
    if request.estimated_cost is not None:
        cost = request.estimated_cost
        if cost.worst_case > cost.current_cap and not _has_budget_approval(request):
            requirements.append(
                BudgetIncreaseApproval(
                    budget_scope=cost.scope,
                    ledger_version=cost.ledger_version,
                    unit=cost.unit,
                    prior_cap=cost.prior_cap if cost.prior_cap is not None else cost.current_cap,
                    authorized_new_cap=cost.worst_case,
                    authorized_delta=cost.worst_case
                    - (cost.prior_cap if cost.prior_cap is not None else cost.current_cap),
                    expires_at=request.approval_expires_at,
                )
            )
    if request.design_approval_required and not _has_design_approval(request):
        if isinstance(request.design_subject, DesignApproval):
            requirements.append(request.design_subject)
        else:
            requirements.append(
                DesignApproval(
                    design_artifact_hash="pending",
                    validation_report_hash="pending",
                    invariant_hashes=(),
                    expires_at=request.approval_expires_at,
                )
            )
    return tuple(requirements)


def _has_budget_approval(request: PolicyRequest) -> bool:
    cost = request.estimated_cost
    if cost is None:
        return False
    return any(
        isinstance(record.subject, BudgetIncreaseApproval)
        and record.status is ApprovalStatus.APPROVED
        and record.subject.budget_scope is cost.scope
        and record.subject.ledger_version == cost.ledger_version
        and record.subject.authorized_new_cap >= cost.worst_case
        for record in _matching_records(request)
    )


def _has_design_approval(request: PolicyRequest) -> bool:
    expected = request.design_subject
    if not isinstance(expected, DesignApproval):
        return False
    return any(
        isinstance(record.subject, DesignApproval)
        and record.status is ApprovalStatus.APPROVED
        and record.subject.design_artifact_hash == expected.design_artifact_hash
        and record.subject.validation_report_hash == expected.validation_report_hash
        and record.subject.invariant_hashes == expected.invariant_hashes
        for record in _matching_records(request)
    )


def _synthetic_operation_approval(
    request: PolicyRequest, permission: PermissionLevel | None = None
) -> OperationApproval:
    binding = _operation_binding(request)
    return OperationApproval(
        operation_idempotency_key=binding.operation_idempotency_key,
        resolved_input_digest=binding.resolved_input_digest,
        artifact_hashes=binding.artifact_hashes,
        capability_id=binding.capability_id,
        capability_contract_version=binding.capability_contract_version,
        connector_id=binding.connector_id or "unbound",
        connector_version=binding.connector_version or "unbound",
        target_environment=binding.target_environment,
        required_permission=permission or binding.required_permission,
        external_state_digest=binding.external_state_digest,
        expires_at=request.approval_expires_at,
    )


class PolicyEngine:
    def __init__(self, rule_order: Sequence[tuple[RuleId, DenyRule]] | None = None) -> None:
        self._rules = tuple(rule_order) if rule_order is not None else DENY_RULES

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        if request.grant_authorization.effective != request.workflow_grants:
            raise ValueError("workflow_grants must copy GrantAuthorization.effective")
        if request.grant_authorization.principal != request.principal:
            raise ValueError("policy principal must match grant authorization principal")

        reasons: set[ReasonCode] = set()
        evaluated: list[str] = []
        for rule_id, rule in self._rules:
            evaluated.append(rule_id)
            reasons.update(rule(request))

        ordered_reasons = sort_reasons(frozenset(reasons))
        if ordered_reasons:
            deny_class = deny_class_for_reasons(frozenset(ordered_reasons))
            decision = Decision.DENY
            return PolicyDecision(
                decision=decision.value,
                reasons=ordered_reasons,
                deny_class=deny_class.value if deny_class else None,
                routing=routing_for(decision, deny_class).value,
                required_permission=request.capability.required_permission,
                approval_requirements=(),
                evaluated_rules=tuple(evaluated),
                decided_at=request.evaluated_at,
            )

        evaluated.append("R16-R19")
        approvals = collect_approval_requirements(request)
        if approvals:
            decision = Decision.REQUIRE_APPROVAL
            return PolicyDecision(
                decision=decision.value,
                reasons=(),
                deny_class=None,
                routing=routing_for(decision, None).value,
                required_permission=request.capability.required_permission,
                approval_requirements=approvals,
                evaluated_rules=tuple(evaluated),
                decided_at=request.evaluated_at,
            )

        decision = Decision.ALLOW
        return PolicyDecision(
            decision=decision.value,
            reasons=(),
            deny_class=None,
            routing=routing_for(decision, None).value,
            required_permission=request.capability.required_permission,
            approval_requirements=(),
            evaluated_rules=tuple((*evaluated, "R21")),
            decided_at=request.evaluated_at,
        )
