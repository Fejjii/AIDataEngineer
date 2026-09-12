"""Map fake Snowflake errors onto architecture failure classes."""

from __future__ import annotations

from aide.domain.failures import FailureClass


class FakeSnowflakeError(RuntimeError):
    def __init__(self, failure: FailureClass, message: str) -> None:
        super().__init__(message)
        self.failure = failure


def map_error(exc: BaseException) -> FailureClass:
    if isinstance(exc, FakeSnowflakeError):
        return exc.failure
    if isinstance(exc, TimeoutError):
        return FailureClass.TIMEOUT
    return FailureClass.CONNECTOR_FAILURE
