"""Pure domain contracts. Imports only the standard library and Pydantic."""

from aide.domain.approvals import (
    ApprovalRecord,
    ApprovalStatus,
    ApprovalSubject,
    BudgetIncreaseApproval,
    DesignApproval,
    OperationApproval,
    OperationBinding,
)
from aide.domain.artifacts import ArtifactProvenance, ExecutionMode
from aide.domain.costs import BudgetScope, CostEstimate, CostUnit
from aide.domain.effects import EffectSemantics
from aide.domain.enums import ApprovalRule, RiskLevel, TargetEnv
from aide.domain.failures import FailureClass
from aide.domain.git import GitChangeClassification
from aide.domain.identity import (
    UnresolvedInputError,
    canonical_json_bytes,
    compute_operation_idempotency_key,
    compute_resolved_input_digest,
    contains_unresolved_placeholder,
)
from aide.domain.permissions import (
    APPROVAL_ELIGIBLE,
    DISABLED_V1,
    PermissionLevel,
)
from aide.domain.principal import (
    AuthenticationSource,
    GrantAuthorization,
    PrincipalRef,
    Role,
)
from aide.domain.sql import AssetKind, AssetRef, SqlClassification, SqlText
from aide.domain.states import (
    LEGAL_TRANSITIONS,
    TERMINAL_WORKFLOW_STATES,
    AttemptOutcome,
    CancellationState,
    DispatchState,
    PhaseRunStatus,
    TaskState,
    WorkflowState,
    is_reachable,
    nonterminal_has_exit,
)
from aide.domain.tasks import (
    MaterializedTask,
    PhaseRunIdentity,
    TaskAttempt,
    TaskTemplate,
    materialize_task,
)
from aide.domain.versions import CapabilityContractRef, ContractSnapshot

__all__ = [
    "APPROVAL_ELIGIBLE",
    "DISABLED_V1",
    "LEGAL_TRANSITIONS",
    "TERMINAL_WORKFLOW_STATES",
    "ApprovalRecord",
    "ApprovalRule",
    "ApprovalStatus",
    "ApprovalSubject",
    "ArtifactProvenance",
    "AssetKind",
    "AssetRef",
    "AttemptOutcome",
    "AuthenticationSource",
    "BudgetIncreaseApproval",
    "BudgetScope",
    "CancellationState",
    "CapabilityContractRef",
    "ContractSnapshot",
    "CostEstimate",
    "CostUnit",
    "DesignApproval",
    "DispatchState",
    "EffectSemantics",
    "ExecutionMode",
    "FailureClass",
    "GitChangeClassification",
    "GrantAuthorization",
    "MaterializedTask",
    "OperationApproval",
    "OperationBinding",
    "PermissionLevel",
    "PhaseRunIdentity",
    "PhaseRunStatus",
    "PrincipalRef",
    "RiskLevel",
    "Role",
    "SqlClassification",
    "SqlText",
    "TargetEnv",
    "TaskAttempt",
    "TaskState",
    "TaskTemplate",
    "UnresolvedInputError",
    "WorkflowState",
    "canonical_json_bytes",
    "compute_operation_idempotency_key",
    "compute_resolved_input_digest",
    "contains_unresolved_placeholder",
    "is_reachable",
    "materialize_task",
    "nonterminal_has_exit",
]
