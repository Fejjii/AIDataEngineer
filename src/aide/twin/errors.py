"""Stable failure codes for deterministic Twin pinning and context assembly."""

from __future__ import annotations

from enum import Enum


class TwinFailureCode(str, Enum):
    AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
    CONTEXT_BOUND_EXCEEDED = "CONTEXT_BOUND_EXCEEDED"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"
    EVIDENCE_CONTAMINATION = "EVIDENCE_CONTAMINATION"
    FRESHNESS_REQUIRED = "FRESHNESS_REQUIRED"
    OUT_OF_SCOPE_ASSET = "OUT_OF_SCOPE_ASSET"
    SNAPSHOT_MEMBER_MISMATCH = "SNAPSHOT_MEMBER_MISMATCH"
    UNSAFE_CONTEXT_VALUE = "UNSAFE_CONTEXT_VALUE"


class TwinValidationError(ValueError):
    """Typed fail-closed error carrying a stable reason code."""

    def __init__(self, code: TwinFailureCode, detail: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {detail}")


__all__ = ["TwinFailureCode", "TwinValidationError"]
