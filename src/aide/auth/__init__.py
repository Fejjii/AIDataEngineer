"""Opaque session, CSRF, trusted auth context, and grant authorization."""

from aide.auth.context import (
    ClientForgeryError,
    TrustedAuthenticationContext,
    authenticate_from_session,
    reject_client_identity,
)
from aide.auth.csrf import (
    SAFE_METHODS,
    CsrfToken,
    CsrfValidationError,
    issue_csrf_token,
    validate_csrf,
)
from aide.auth.grants import (
    ENVIRONMENT_POLICY_VERSION,
    GrantAuthorizer,
    GrantForgeryError,
)
from aide.auth.session import OpaqueSession, SessionExpiredError

__all__ = [
    "ENVIRONMENT_POLICY_VERSION",
    "SAFE_METHODS",
    "ClientForgeryError",
    "CsrfToken",
    "CsrfValidationError",
    "GrantAuthorizer",
    "GrantForgeryError",
    "OpaqueSession",
    "SessionExpiredError",
    "TrustedAuthenticationContext",
    "authenticate_from_session",
    "issue_csrf_token",
    "reject_client_identity",
    "validate_csrf",
]
