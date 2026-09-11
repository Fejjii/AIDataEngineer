"""Trusted authentication context created only from a server session."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from aide.auth.session import OpaqueSession, SessionExpiredError
from aide.domain.principal import PrincipalRef


class ClientForgeryError(PermissionError):
    """Client supplied principal, roles, or effective grants."""


_FORBIDDEN_CLIENT_FIELDS = frozenset(
    {
        "principal_id",
        "roles",
        "effective",
        "effective_grants",
        "grant_authorization",
        "authentication_source",
    }
)


class TrustedAuthenticationContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: PrincipalRef
    session_id: UUID
    authenticated_at: datetime
    csrf_required_for_mutations: bool = True


def authenticate_from_session(
    session: OpaqueSession, *, now: datetime
) -> TrustedAuthenticationContext:
    if session.is_expired(now):
        raise SessionExpiredError("session expired")
    principal = PrincipalRef(
        principal_id=session.principal_id,
        authentication_source="LOCAL_SESSION",
        roles=session.roles,
        session_id=session.session_id,
    )
    return TrustedAuthenticationContext(
        principal=principal,
        session_id=session.session_id,
        authenticated_at=now,
    )


def reject_client_identity(payload: Mapping[str, Any]) -> None:
    """Reject caller-supplied actor, roles, or effective grants."""
    keys = {str(key) for key in payload}
    overlap = keys & _FORBIDDEN_CLIENT_FIELDS
    if overlap:
        raise ClientForgeryError(
            f"client must not supply trusted identity fields: {sorted(overlap)}"
        )
    nested = payload.get("principal")
    if isinstance(nested, Mapping):
        reject_client_identity(nested)
