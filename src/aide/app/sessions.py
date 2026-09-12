"""Local MVP session issuance and cookie authentication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.auth.context import TrustedAuthenticationContext, authenticate_from_session
from aide.auth.csrf import CsrfValidationError, issue_csrf_token, validate_csrf
from aide.auth.session import (
    CSRF_HEADER,
    SESSION_COOKIE,
    IssuedLocalSession,
    OpaqueSession,
    SessionExpiredError,
    SessionInvalidError,
    SessionMissingError,
    digest_session_token,
    issue_session_token,
)
from aide.domain.principal import PrincipalRef, Role
from aide.persistence.repositories import SessionRepository

__all__ = [
    "CSRF_HEADER",
    "SESSION_COOKIE",
    "IssuedLocalSession",
    "LocalSessionService",
    "SessionInvalidError",
    "SessionMissingError",
]


class LocalSessionService:
    """Persist opaque token digests and reconstruct PrincipalRef from PostgreSQL."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        csrf_secret: bytes,
        ttl: timedelta = timedelta(hours=8),
    ) -> None:
        self._sessions = session_factory
        self._csrf_secret = csrf_secret
        self._ttl = ttl

    @property
    def csrf_secret(self) -> bytes:
        return self._csrf_secret

    async def issue(
        self,
        *,
        now: datetime | None = None,
        expires_at: datetime | None = None,
        roles: frozenset[Role] | None = None,
    ) -> IssuedLocalSession:
        current = _naive(now or datetime.now(UTC))
        expiry = _naive(expires_at) if expires_at is not None else current + self._ttl
        principal = PrincipalRef(
            principal_id=uuid4(),
            authentication_source="LOCAL_SESSION",
            roles=roles or frozenset({Role.OPERATOR, Role.APPROVER}),
            session_id=uuid4(),
        )
        opaque = issue_session_token()
        session = OpaqueSession(
            session_id=principal.session_id,
            principal_id=principal.principal_id,
            roles=principal.roles,
            created_at=current,
            expires_at=expiry,
            token_digest=digest_session_token(opaque),
        )
        csrf = issue_csrf_token(session, secret=self._csrf_secret)
        async with self._sessions() as db, db.begin():
            await SessionRepository(db).add(
                principal=principal,
                opaque_token_digest=session.token_digest,
                csrf_token_digest=digest_session_token(csrf.token),
                expires_at=expiry,
            )
        return IssuedLocalSession(
            opaque_token=opaque,
            csrf_token=csrf.token,
            principal=principal,
            expires_at=expiry,
        )

    async def authenticate(
        self,
        opaque_token: str | None,
        *,
        csrf_token: str | None,
        method: str,
        now: datetime | None = None,
    ) -> TrustedAuthenticationContext:
        if not opaque_token:
            raise SessionMissingError("session cookie is required")
        current = _naive(now or datetime.now(UTC))
        digest = digest_session_token(opaque_token)
        async with self._sessions() as db:
            row = await SessionRepository(db).get_by_token_digest(digest)
        if row is None or row.revoked_at is not None:
            raise SessionInvalidError("session is not recognized")
        session = OpaqueSession(
            session_id=row.session_id,
            principal_id=row.principal_id,
            roles=frozenset(Role(item) for item in row.roles),
            created_at=row.created_at,
            expires_at=row.expires_at,
            token_digest=row.opaque_token_digest,
        )
        if session.is_expired(current):
            raise SessionExpiredError("session expired")
        if csrf_token is None or csrf_token == "":
            raise CsrfValidationError("CSRF token is required")
        if digest_session_token(csrf_token) != row.csrf_token_digest:
            raise CsrfValidationError("CSRF token does not match the session")
        validate_csrf(session=session, token=csrf_token, method=method, secret=self._csrf_secret)
        return authenticate_from_session(session, now=current)


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value
