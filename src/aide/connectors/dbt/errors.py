"""Deterministic dbt failure classification. No LLM."""

from __future__ import annotations

from aide.connectors.snowflake.errors import map_error as map_warehouse_error
from aide.domain.failures import FailureClass

COMPILE_TYPE_NAMES = frozenset(
    {
        "CompilationError",
        "ParsingError",
        "CompilationException",
        "DbtConfigError",
        "DbtProjectError",
        "DbtProfileError",
        "YamlParseDictError",
        "YamlLoadError",
        "DuplicateResourceNameError",
        "TargetNotFoundError",
        "RefBadContextError",
        "RefArgsError",
        "GraphDependencyNotFoundError",
        "MissingRelationError",
    }
)
DATABASE_TYPE_NAMES = frozenset(
    {
        "DbtDatabaseError",
        "DatabaseError",
        "DatabaseException",
        "BinderException",
        "CatalogException",
        "ParserException",
        "InvalidInputException",
    }
)
RUNTIME_TYPE_NAMES = frozenset({"DbtRuntimeError", "RuntimeError", "DbtInternalError"})


class DbtMappedError(RuntimeError):
    """Connector-local classified error. Message must already be sanitized."""

    def __init__(
        self,
        failure: FailureClass,
        message: str,
        *,
        reason_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure = failure
        self.reason_code = reason_code


class DbtTimeoutError(DbtMappedError):
    def __init__(self, message: str = "dbt invocation timed out") -> None:
        super().__init__(FailureClass.TIMEOUT, message, reason_code="TIMEOUT")


class DbtProcessTerminatedError(DbtMappedError):
    def __init__(
        self, message: str = "dbt process terminated", *, signal: int | None = None
    ) -> None:
        suffix = f" signal={signal}" if signal is not None else ""
        super().__init__(
            FailureClass.CONNECTOR_FAILURE,
            f"{message}{suffix}".strip(),
            reason_code="PROCESS_TERMINATED",
        )
        self.signal = signal


class _MessageError(Exception):
    """Adapter used so warehouse mapping can inspect a sanitized message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.msg = message
        self.raw_msg = message
        self.message = message


def map_error(exc: BaseException) -> FailureClass:
    if isinstance(exc, DbtMappedError):
        return exc.failure
    if isinstance(exc, TimeoutError):
        return FailureClass.TIMEOUT
    name = type(exc).__name__
    if name in COMPILE_TYPE_NAMES:
        return FailureClass.DBT_COMPILE
    if name in DATABASE_TYPE_NAMES:
        mapped = map_warehouse_error(_MessageError(str(exc)))
        if mapped is FailureClass.CONNECTOR_FAILURE:
            return FailureClass.DBT_RUNTIME
        return mapped
    if name in RUNTIME_TYPE_NAMES:
        warehouse = map_warehouse_error(_MessageError(str(exc)))
        if warehouse not in {FailureClass.CONNECTOR_FAILURE, FailureClass.UNKNOWN}:
            return warehouse
        return FailureClass.DBT_RUNTIME
    if "timeout" in str(exc).lower():
        return FailureClass.TIMEOUT
    return FailureClass.CONNECTOR_FAILURE


def map_exception_name(name: str | None, message: str) -> FailureClass:
    if not name:
        return FailureClass.DBT_RUNTIME
    dummy = type(name, (Exception,), {})
    return map_error(dummy(message))


def map_run_result_status(status: str, message: str | None) -> FailureClass | None:
    normalized = status.lower()
    if normalized in {"pass", "success", "skipped", "warn"}:
        return None
    if normalized == "fail":
        return FailureClass.DBT_TEST
    if message:
        warehouse = map_warehouse_error(_MessageError(message))
        if warehouse not in {FailureClass.CONNECTOR_FAILURE, FailureClass.UNKNOWN}:
            return warehouse
    if normalized == "error":
        return FailureClass.DBT_RUNTIME
    return FailureClass.DBT_RUNTIME
