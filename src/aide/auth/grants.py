"""Server-side grant authorizer. Client effective grants are never trusted."""

from __future__ import annotations

from datetime import datetime

from aide.auth.context import ClientForgeryError
from aide.domain.enums import TargetEnv
from aide.domain.permissions import DISABLED_V1, PermissionLevel
from aide.domain.principal import GrantAuthorization, PrincipalRef, Role

ENVIRONMENT_POLICY_VERSION = "aide-env-policy-v1"

OPERATOR_DEFAULT_GRANTS: frozenset[PermissionLevel] = frozenset(
    {
        PermissionLevel.READ,
        PermissionLevel.DEVELOPMENT_EXECUTE,
        PermissionLevel.DEVELOPMENT_WRITE,
        PermissionLevel.GIT_WRITE,
    }
)


class GrantForgeryError(ClientForgeryError):
    pass


class GrantAuthorizer:
    """Intersect requested grants with role, environment, and disabled V1 set."""

    def authorize(
        self,
        principal: PrincipalRef,
        requested: frozenset[PermissionLevel],
        *,
        target_environment: TargetEnv,
        decided_at: datetime,
        client_supplied_effective: frozenset[PermissionLevel] | None = None,
        client_supplied_principal: PrincipalRef | None = None,
    ) -> GrantAuthorization:
        if client_supplied_effective is not None:
            raise GrantForgeryError("client supplied effective grants are not trusted")
        if client_supplied_principal is not None:
            raise GrantForgeryError("client supplied PrincipalRef is not trusted")
        role_grants = frozenset[PermissionLevel]()
        if Role.OPERATOR in principal.roles:
            role_grants = OPERATOR_DEFAULT_GRANTS
        effective = requested & role_grants
        effective -= DISABLED_V1
        if target_environment is TargetEnv.PROD:
            effective = frozenset()
        return GrantAuthorization(
            principal=principal,
            requested=requested,
            effective=effective,
            environment_policy_version=ENVIRONMENT_POLICY_VERSION,
            decided_at=decided_at,
        )
