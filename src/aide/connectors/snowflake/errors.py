"""Map Snowflake vendor errors onto architecture failure classes."""

from __future__ import annotations

import re
from typing import Any

from aide.domain.failures import FailureClass

# Recorded Snowflake errno → failure class (docs/CONNECTOR_ARCHITECTURE.md §5.1).
ERRNO_TO_FAILURE: dict[int, FailureClass] = {
    1003: FailureClass.SQL_SYNTAX,  # 001003
    2003: FailureClass.MISSING_OBJECT,  # 002003
    904: FailureClass.SCHEMA_MISMATCH,  # 000904 invalid identifier
    100038: FailureClass.TYPE_MISMATCH,
    100040: FailureClass.TYPE_MISMATCH,
    3001: FailureClass.PERMISSION_FAILURE,  # 003001
    1011: FailureClass.PERMISSION_FAILURE,  # 001011
    630: FailureClass.TIMEOUT,  # 000630
    604: FailureClass.TIMEOUT,  # cancelled
    390114: FailureClass.TRANSIENT_PROVIDER,
    606: FailureClass.RESOURCE_LIMIT,  # resource monitor / quota
    608: FailureClass.RESOURCE_LIMIT,
}

_SQL_SYNTAX_RE = re.compile(r"syntax error|unexpected|parse error", re.I)
_MISSING_RE = re.compile(
    r"does not exist|does not exist or not authorized|object .* not found", re.I
)
_SCHEMA_RE = re.compile(
    r"invalid identifier|unknown column|invalid column|referenced column|"
    r"column \".+\" referenced|not found in from clause|"
    r"cannot be referenced before it is defined",
    re.I,
)
_TYPE_RE = re.compile(
    r"numeric value .* is not recognized|timestamp .* is not recognized|is not recognized|"
    r"data type|incompatible type|type mismatch",
    re.I,
)
_PERM_RE = re.compile(
    r"insufficient privilege|not authorized|permission denied|access denied|privilege",
    re.I,
)
_TIMEOUT_RE = re.compile(r"timeout|timed out|canceled|cancelled|statement reached time", re.I)
_TRANSIENT_RE = re.compile(
    r"try again|temporarily unavailable|jwt|token.*(expired|invalid)|rate limit|"
    r"connection reset|could not connect|network",
    re.I,
)
_RESOURCE_RE = re.compile(r"resource monitor|quota|credit|warehouse .* suspended over", re.I)


class SnowflakeMappedError(RuntimeError):
    """Connector-local error already classified. Safe message only; never secrets."""

    def __init__(
        self,
        failure: FailureClass,
        message: str,
        *,
        vendor_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.vendor_code = vendor_code


class FakeSnowflakeError(SnowflakeMappedError):
    """Deterministic fake-connector failure used by contract and slice tests."""


def _errno(exc: BaseException) -> int | None:
    raw: Any = getattr(exc, "errno", None)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None


def _message(exc: BaseException) -> str:
    for attr in ("raw_msg", "msg", "message"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    return str(exc)


def _sqlstate(exc: BaseException) -> str | None:
    value = getattr(exc, "sqlstate", None)
    return str(value) if value is not None else None


def sanitize_error_message(message: str, *, limit: int = 400) -> str:
    """Strip key material and truncate. Env var names are allowed."""
    text = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED_KEY]",
        message,
        flags=re.S,
    )
    text = re.sub(
        r"(?i)(private[_-]?key|password|secret|token)\s*[:=]\s*\S+", r"\1=[REDACTED]", text
    )
    return text[:limit]


def map_error(exc: BaseException) -> FailureClass:
    if isinstance(exc, SnowflakeMappedError):
        return exc.failure
    if isinstance(exc, TimeoutError):
        return FailureClass.TIMEOUT
    errno = _errno(exc)
    if errno is not None and errno in ERRNO_TO_FAILURE:
        return ERRNO_TO_FAILURE[errno]
    padded = None if errno is None else f"{errno:06d}"
    if padded == "001003":
        return FailureClass.SQL_SYNTAX
    message = _message(exc)
    sqlstate = _sqlstate(exc)
    if sqlstate in {"42601", "42000"} and _SQL_SYNTAX_RE.search(message):
        return FailureClass.SQL_SYNTAX
    if _RESOURCE_RE.search(message):
        return FailureClass.RESOURCE_LIMIT
    if _TIMEOUT_RE.search(message):
        return FailureClass.TIMEOUT
    if _PERM_RE.search(message):
        return FailureClass.PERMISSION_FAILURE
    if _MISSING_RE.search(message):
        return FailureClass.MISSING_OBJECT
    if _SCHEMA_RE.search(message):
        return FailureClass.SCHEMA_MISMATCH
    if _TYPE_RE.search(message):
        return FailureClass.TYPE_MISMATCH
    if _SQL_SYNTAX_RE.search(message):
        return FailureClass.SQL_SYNTAX
    if _TRANSIENT_RE.search(message):
        return FailureClass.TRANSIENT_PROVIDER
    name = type(exc).__name__.lower()
    if "operational" in name or "interface" in name or "network" in name:
        return FailureClass.TRANSIENT_PROVIDER
    return FailureClass.CONNECTOR_FAILURE


def raise_mapped(exc: BaseException) -> None:
    if isinstance(exc, SnowflakeMappedError):
        raise exc
    raise SnowflakeMappedError(
        map_error(exc),
        sanitize_error_message(_message(exc)),
        vendor_code=str(_errno(exc)) if _errno(exc) is not None else None,
    ) from exc
