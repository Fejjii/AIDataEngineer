"""Trusted principal and server-derived grant authorization contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.permissions import PermissionLevel


class Role(str, Enum):
    OPERATOR = "operator"
    APPROVER = "approver"


AuthenticationSource = Literal["LOCAL_SESSION"]


class PrincipalRef(BaseModel):
    """Server-created actor identity. Clients cannot submit this object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_id: UUID
    authentication_source: AuthenticationSource
    roles: frozenset[Role]
    session_id: UUID


class GrantAuthorization(BaseModel):
    """Trusted server-side grant decision. ``effective`` is never client-set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: PrincipalRef
    requested: frozenset[PermissionLevel]
    effective: frozenset[PermissionLevel]
    environment_policy_version: str = Field(min_length=1)
    decided_at: datetime
