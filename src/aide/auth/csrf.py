"""Session-bound CSRF contract for mutating requests."""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.auth.session import OpaqueSession

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CsrfValidationError(PermissionError):
    pass


class CsrfToken(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    token: str = Field(min_length=16)


def issue_csrf_token(session: OpaqueSession, *, secret: bytes) -> CsrfToken:
    material = hmac.new(secret, str(session.session_id).encode("utf-8"), hashlib.sha256)
    return CsrfToken(session_id=session.session_id, token=material.hexdigest())


def validate_csrf(
    *,
    session: OpaqueSession,
    token: str,
    method: str,
    secret: bytes,
) -> None:
    if method.upper() in SAFE_METHODS:
        return
    expected = issue_csrf_token(session, secret=secret)
    if not hmac.compare_digest(expected.token, token):
        raise CsrfValidationError("CSRF token does not match the session")
    if expected.session_id != session.session_id:
        raise CsrfValidationError("CSRF token session mismatch")
