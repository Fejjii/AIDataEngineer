"""Sanitize dbt logs and artifacts. Never emit secret values."""

from __future__ import annotations

import re
from collections.abc import Iterable

_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.S,
)
_ASSIGNMENT = re.compile(r"(?i)(private[_-]?key|password|secret|token|passphrase)\s*[:=]\s*\S+")
_CONNECTION = re.compile(r"(?i)(account|user)=([^\s;]+)")

ALLOWED_NAME_FRAGMENTS = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER_DEV",
    "SNOWFLAKE_PRIVATE_KEY_DEV",
    "SNOWFLAKE_WAREHOUSE_DEV",
    "SNOWFLAKE_USER_RO",
    "SNOWFLAKE_PRIVATE_KEY_RO",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    "SECRET_UNRESOLVED",
)


def sanitize_text(text: str, *, extra_secrets: Iterable[str] = (), limit: int = 8000) -> str:
    redacted = _KEY_BLOCK.sub("[REDACTED_KEY]", text)
    redacted = _ASSIGNMENT.sub(r"\1=[REDACTED]", redacted)
    redacted = _CONNECTION.sub(r"\1=[REDACTED]", redacted)
    for secret in extra_secrets:
        if secret and secret not in ALLOWED_NAME_FRAGMENTS:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted[:limit]


def env_keys_only(env: dict[str, str], *, secret_names: Iterable[str]) -> dict[str, str]:
    """Return a loggable env map: secret names become REDACTED, other values kept."""
    secrets = set(secret_names)
    safe: dict[str, str] = {}
    for key, value in env.items():
        if key in secrets:
            safe[key] = "[REDACTED]"
        else:
            safe[key] = sanitize_text(value, extra_secrets=())
    return safe
