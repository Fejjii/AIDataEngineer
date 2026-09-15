"""Explicit normalization of intentionally variable Interview MVP fields."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from aide.domain.identity import canonical_json_bytes

UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?"
)
SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")

# Digests that encode identifiers (snapshot UUID, evidence_ref_id) are re-hashed
# after substitution. Content-addressed hashes of SQL/plan bodies are kept.
_IDENTITY_DIGEST_KEYS = frozenset(
    {
        "estate_context_sha256",
        "bundle_sha256",
        "manifest_sha256",
        "pinned_snapshot_digest",
        "producer_operation_key",
        "resolved_input_digest",
        "operation_idempotency_key",
        "identity",
    }
)


def normalize_text(value: str) -> str:
    replaced = UUID_RE.sub("<uuid>", value)
    replaced = ISO_TIMESTAMP_RE.sub("<timestamp>", replaced)
    return replaced


def normalize_value(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            str(item_key): normalize_value(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [normalize_value(item, key=key) for item in value]
    if isinstance(value, str):
        if key in _IDENTITY_DIGEST_KEYS and SHA256_RE.fullmatch(value):
            return "<identity-digest>"
        return normalize_text(value)
    return value


def normalized_digest(value: Any) -> str:
    payload = normalize_value(value)
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


__all__ = ["normalize_text", "normalize_value", "normalized_digest"]
