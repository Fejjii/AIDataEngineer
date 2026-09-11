"""Canonical unordered permission grants.

``PermissionLevel`` is a set of distinct grants with no ranking. Anything that
compares two grants with ``<``, ``>``, ``<=``, ``>=`` or ``max()`` is a design
violation.
"""

from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    """Distinct grants. Membership only; no ordering."""

    READ = "READ"
    DEVELOPMENT_EXECUTE = "DEVELOPMENT_EXECUTE"
    DEVELOPMENT_WRITE = "DEVELOPMENT_WRITE"
    GIT_WRITE = "GIT_WRITE"
    STAGING_DEPLOY = "STAGING_DEPLOY"
    PRODUCTION_WRITE = "PRODUCTION_WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    SECURITY = "SECURITY"

    def __lt__(self, other: object) -> bool:
        raise TypeError("PermissionLevel grants have no ordering")

    def __le__(self, other: object) -> bool:
        raise TypeError("PermissionLevel grants have no ordering")

    def __gt__(self, other: object) -> bool:
        raise TypeError("PermissionLevel grants have no ordering")

    def __ge__(self, other: object) -> bool:
        raise TypeError("PermissionLevel grants have no ordering")


APPROVAL_ELIGIBLE: frozenset[PermissionLevel] = frozenset(
    {
        PermissionLevel.STAGING_DEPLOY,
        PermissionLevel.DESTRUCTIVE,
    }
)

DISABLED_V1: frozenset[PermissionLevel] = frozenset(
    {
        PermissionLevel.PRODUCTION_WRITE,
        PermissionLevel.INFRASTRUCTURE,
        PermissionLevel.SECURITY,
    }
)
