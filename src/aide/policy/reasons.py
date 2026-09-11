"""Reason codes, deny classes, and authoritative severity."""

from __future__ import annotations

from enum import Enum


class ReasonCode(str, Enum):
    UNKNOWN_TARGET = "UNKNOWN_TARGET"
    CONNECTOR_UNAVAILABLE = "CONNECTOR_UNAVAILABLE"
    CONNECTOR_PERMISSION_MISSING = "CONNECTOR_PERMISSION_MISSING"
    SECRET_UNRESOLVED = "SECRET_UNRESOLVED"
    CONTRACT_VERSION_UNAVAILABLE = "CONTRACT_VERSION_UNAVAILABLE"
    PERM_NOT_GRANTED = "PERM_NOT_GRANTED"
    PERMISSION_NOT_ALLOWED_FOR_CONNECTOR = "PERMISSION_NOT_ALLOWED_FOR_CONNECTOR"
    READ_ONLY_IDENTITY_REQUIRED = "READ_ONLY_IDENTITY_REQUIRED"
    ENV_MISMATCH = "ENV_MISMATCH"
    PROD_DISABLED_V1 = "PROD_DISABLED_V1"
    SQL_UNPARSEABLE = "SQL_UNPARSEABLE"
    SQL_DESTRUCTIVE = "SQL_DESTRUCTIVE"
    SQL_SECURITY = "SQL_SECURITY"
    SQL_UNSAFE_FUNCTION = "SQL_UNSAFE_FUNCTION"
    SQL_UNSAFE_CONSTRUCT = "SQL_UNSAFE_CONSTRUCT"
    SQL_MULTI = "SQL_MULTI"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    WRITE_OUTSIDE_NAMESPACE = "WRITE_OUTSIDE_NAMESPACE"
    READ_ONLY_REQUIRED = "READ_ONLY_REQUIRED"
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
    PROTECTED_BRANCH = "PROTECTED_BRANCH"
    SECRET_IN_DIFF = "SECRET_IN_DIFF"
    MOCK_PROVENANCE_TO_REAL_TARGET = "MOCK_PROVENANCE_TO_REAL_TARGET"


class DenyClass(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    SCOPE = "SCOPE"
    SECURITY = "SECURITY"


class Routing(str, Enum):
    EXECUTE = "EXECUTE"
    APPROVAL = "APPROVAL"
    PARK = "PARK"
    FAIL_CLOSED = "FAIL_CLOSED"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    DENY = "DENY"


REASON_CLASS: dict[ReasonCode, DenyClass] = {
    ReasonCode.CONNECTOR_UNAVAILABLE: DenyClass.ENVIRONMENTAL,
    ReasonCode.CONNECTOR_PERMISSION_MISSING: DenyClass.ENVIRONMENTAL,
    ReasonCode.SECRET_UNRESOLVED: DenyClass.ENVIRONMENTAL,
    ReasonCode.CONTRACT_VERSION_UNAVAILABLE: DenyClass.ENVIRONMENTAL,
    ReasonCode.UNKNOWN_TARGET: DenyClass.SCOPE,
    ReasonCode.PERM_NOT_GRANTED: DenyClass.SCOPE,
    ReasonCode.PERMISSION_NOT_ALLOWED_FOR_CONNECTOR: DenyClass.SCOPE,
    ReasonCode.READ_ONLY_IDENTITY_REQUIRED: DenyClass.SCOPE,
    ReasonCode.ENV_MISMATCH: DenyClass.SCOPE,
    ReasonCode.PROD_DISABLED_V1: DenyClass.SCOPE,
    ReasonCode.SCOPE_VIOLATION: DenyClass.SCOPE,
    ReasonCode.WRITE_OUTSIDE_NAMESPACE: DenyClass.SCOPE,
    ReasonCode.READ_ONLY_REQUIRED: DenyClass.SCOPE,
    ReasonCode.PROVENANCE_MISMATCH: DenyClass.SCOPE,
    ReasonCode.MOCK_PROVENANCE_TO_REAL_TARGET: DenyClass.SCOPE,
    ReasonCode.SQL_UNPARSEABLE: DenyClass.SECURITY,
    ReasonCode.SQL_DESTRUCTIVE: DenyClass.SECURITY,
    ReasonCode.SQL_SECURITY: DenyClass.SECURITY,
    ReasonCode.SQL_UNSAFE_FUNCTION: DenyClass.SECURITY,
    ReasonCode.SQL_UNSAFE_CONSTRUCT: DenyClass.SECURITY,
    ReasonCode.SQL_MULTI: DenyClass.SECURITY,
    ReasonCode.PROTECTED_BRANCH: DenyClass.SECURITY,
    ReasonCode.SECRET_IN_DIFF: DenyClass.SECURITY,
}

DENY_CLASS_SEVERITY: dict[DenyClass, int] = {
    DenyClass.ENVIRONMENTAL: 1,
    DenyClass.SCOPE: 2,
    DenyClass.SECURITY: 3,
}

REASON_CANONICAL_ORDER: tuple[ReasonCode, ...] = (
    ReasonCode.UNKNOWN_TARGET,
    ReasonCode.CONNECTOR_UNAVAILABLE,
    ReasonCode.CONNECTOR_PERMISSION_MISSING,
    ReasonCode.SECRET_UNRESOLVED,
    ReasonCode.CONTRACT_VERSION_UNAVAILABLE,
    ReasonCode.PERM_NOT_GRANTED,
    ReasonCode.PERMISSION_NOT_ALLOWED_FOR_CONNECTOR,
    ReasonCode.READ_ONLY_IDENTITY_REQUIRED,
    ReasonCode.ENV_MISMATCH,
    ReasonCode.PROD_DISABLED_V1,
    ReasonCode.SQL_UNPARSEABLE,
    ReasonCode.SQL_DESTRUCTIVE,
    ReasonCode.SQL_SECURITY,
    ReasonCode.SQL_UNSAFE_FUNCTION,
    ReasonCode.SQL_UNSAFE_CONSTRUCT,
    ReasonCode.SQL_MULTI,
    ReasonCode.SCOPE_VIOLATION,
    ReasonCode.WRITE_OUTSIDE_NAMESPACE,
    ReasonCode.READ_ONLY_REQUIRED,
    ReasonCode.PROVENANCE_MISMATCH,
    ReasonCode.PROTECTED_BRANCH,
    ReasonCode.SECRET_IN_DIFF,
    ReasonCode.MOCK_PROVENANCE_TO_REAL_TARGET,
)


def sort_reasons(reasons: frozenset[ReasonCode]) -> tuple[ReasonCode, ...]:
    order = {code: index for index, code in enumerate(REASON_CANONICAL_ORDER)}
    return tuple(sorted(reasons, key=lambda code: order[code]))


def deny_class_for_reasons(reasons: frozenset[ReasonCode]) -> DenyClass | None:
    if not reasons:
        return None
    classes = {REASON_CLASS[code] for code in reasons}
    return max(classes, key=lambda item: DENY_CLASS_SEVERITY[item])


def routing_for(decision: Decision, deny_class: DenyClass | None) -> Routing:
    if decision is Decision.ALLOW:
        return Routing.EXECUTE
    if decision is Decision.REQUIRE_APPROVAL:
        return Routing.APPROVAL
    if deny_class is DenyClass.ENVIRONMENTAL:
        return Routing.PARK
    return Routing.FAIL_CLOSED
