"""Operation identity. Impossible before resolved validated input exists."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from aide.domain.enums import TargetEnv

OPERATION_IDENTITY_PREFIX = "aide-op-v2"


class UnresolvedInputError(ValueError):
    """Raised when operation identity is requested before validated input exists."""


def contains_unresolved_placeholder(value: object) -> bool:
    """Detect ``$from`` placeholders that forbid materialization."""
    if isinstance(value, Mapping):
        if "$from" in value:
            return True
        return any(contains_unresolved_placeholder(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_unresolved_placeholder(item) for item in value)
    return False


def canonical_json_bytes(value: object) -> bytes:
    """Canonical JSON serialization used for resolved-input digests."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "value"):
        return value.value
    raise TypeError(f"not JSON-serializable: {type(value)!r}")


def compute_resolved_input_digest(validated_input: BaseModel | Mapping[str, Any]) -> str:
    if isinstance(validated_input, BaseModel):
        payload: object = validated_input.model_dump(mode="json")
    else:
        payload = dict(validated_input)
    if contains_unresolved_placeholder(payload):
        raise UnresolvedInputError(
            "resolved input still contains $from placeholders; operation identity is impossible"
        )
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def compute_operation_idempotency_key(
    *,
    workflow_id: UUID,
    phase_run_id: UUID,
    local_id: str,
    capability_id: str,
    capability_contract_version: int,
    connector_id: str | None,
    connector_version: str | None,
    target_environment: TargetEnv | None,
    resolved_input_digest: str,
) -> str:
    """Stable logical-operation identity. Attempt number is never included."""
    if not resolved_input_digest or len(resolved_input_digest) != 64:
        raise UnresolvedInputError(
            "operation identity requires a 64-hex resolved_input_digest from validated input"
        )
    if contains_unresolved_placeholder(local_id):
        raise UnresolvedInputError("local_id must be fully resolved")
    payload = "\x1f".join(
        [
            OPERATION_IDENTITY_PREFIX,
            str(workflow_id),
            str(phase_run_id),
            local_id,
            capability_id,
            str(capability_contract_version),
            connector_id or "",
            connector_version or "",
            target_environment.value if target_environment is not None else "",
            resolved_input_digest,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
