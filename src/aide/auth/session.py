"""Opaque local session contract. Token values are not stored in the clear."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.principal import Role


class SessionExpiredError(ValueError):
    pass


class OpaqueSession(BaseModel):
    """Server-side session. Clients receive only an opaque cookie handle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: UUID
    principal_id: UUID
    roles: frozenset[Role]
    created_at: datetime
    expires_at: datetime
    token_digest: str = Field(min_length=64, max_length=64)

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at


def digest_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session_token() -> str:
    return secrets.token_urlsafe(32)
