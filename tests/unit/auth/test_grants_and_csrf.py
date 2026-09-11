from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from tests.helpers import principal, utcnow

from aide.auth.context import ClientForgeryError, authenticate_from_session, reject_client_identity
from aide.auth.csrf import CsrfValidationError, issue_csrf_token, validate_csrf
from aide.auth.grants import GrantAuthorizer, GrantForgeryError
from aide.auth.session import OpaqueSession, digest_session_token
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel
from aide.domain.principal import Role


def test_client_cannot_forge_principal_or_effective_grants() -> None:
    with pytest.raises(ClientForgeryError):
        reject_client_identity({"principal_id": str(uuid4()), "requested": ["READ"]})
    with pytest.raises(ClientForgeryError):
        reject_client_identity({"effective": ["SECURITY"]})
    with pytest.raises(ClientForgeryError):
        reject_client_identity({"principal": {"roles": ["operator"]}})
    reject_client_identity({"requested": ["READ"]})

    actor = principal()
    authorizer = GrantAuthorizer()
    with pytest.raises(GrantForgeryError):
        authorizer.authorize(
            actor,
            frozenset({PermissionLevel.READ}),
            target_environment=TargetEnv.DEV,
            decided_at=utcnow(),
            client_supplied_effective=frozenset({PermissionLevel.SECURITY}),
        )
    with pytest.raises(GrantForgeryError):
        authorizer.authorize(
            actor,
            frozenset({PermissionLevel.READ}),
            target_environment=TargetEnv.DEV,
            decided_at=utcnow(),
            client_supplied_principal=principal(),
        )
    decision = authorizer.authorize(
        actor,
        frozenset({PermissionLevel.READ, PermissionLevel.SECURITY, PermissionLevel.STAGING_DEPLOY}),
        target_environment=TargetEnv.DEV,
        decided_at=utcnow(),
    )
    assert PermissionLevel.READ in decision.effective
    assert PermissionLevel.SECURITY not in decision.effective
    assert PermissionLevel.STAGING_DEPLOY not in decision.effective


def test_opaque_session_creates_trusted_context_and_csrf_guards_mutations() -> None:
    now = datetime.now(UTC)
    token = "opaque-session-token"
    session = OpaqueSession(
        session_id=uuid4(),
        principal_id=uuid4(),
        roles=frozenset({Role.OPERATOR}),
        created_at=now,
        expires_at=now + timedelta(hours=1),
        token_digest=digest_session_token(token),
    )
    context = authenticate_from_session(session, now=now)
    assert context.principal.session_id == session.session_id
    assert context.principal.authentication_source == "LOCAL_SESSION"
    secret = b"csrf-secret"
    csrf = issue_csrf_token(session, secret=secret)
    validate_csrf(session=session, token=csrf.token, method="GET", secret=secret)
    validate_csrf(session=session, token=csrf.token, method="POST", secret=secret)
    with pytest.raises(CsrfValidationError):
        validate_csrf(session=session, token="nope", method="POST", secret=secret)
