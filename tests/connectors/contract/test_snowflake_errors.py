from __future__ import annotations

import json
from pathlib import Path

from aide.connectors.snowflake.errors import ERRNO_TO_FAILURE, map_error
from aide.domain.failures import FailureClass

FIXTURE = Path(__file__).parent / "fixtures" / "snowflake_error_codes.json"

REQUIRED_CATEGORIES = {
    FailureClass.SQL_SYNTAX,
    FailureClass.MISSING_OBJECT,
    FailureClass.SCHEMA_MISMATCH,
    FailureClass.TYPE_MISMATCH,
    FailureClass.PERMISSION_FAILURE,
    FailureClass.TIMEOUT,
    FailureClass.TRANSIENT_PROVIDER,
    FailureClass.RESOURCE_LIMIT,
}


class _VendorError(Exception):
    def __init__(self, errno: int | None, sqlstate: str | None, message: str) -> None:
        super().__init__(message)
        self.errno = errno
        self.sqlstate = sqlstate
        self.msg = message
        self.raw_msg = message


def test_recorded_error_fixtures_cover_required_categories() -> None:
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    mapped = {FailureClass(item["expected"]) for item in records}
    assert mapped >= REQUIRED_CATEGORIES
    for item in records:
        exc = _VendorError(item["errno"], item["sqlstate"], item["message"])
        assert map_error(exc) is FailureClass(item["expected"])


def test_errno_table_matches_architecture_codes() -> None:
    assert ERRNO_TO_FAILURE[1003] is FailureClass.SQL_SYNTAX
    assert ERRNO_TO_FAILURE[2003] is FailureClass.MISSING_OBJECT
    assert ERRNO_TO_FAILURE[904] is FailureClass.SCHEMA_MISMATCH
    assert ERRNO_TO_FAILURE[100038] is FailureClass.TYPE_MISMATCH
    assert ERRNO_TO_FAILURE[100040] is FailureClass.TYPE_MISMATCH
    assert ERRNO_TO_FAILURE[3001] is FailureClass.PERMISSION_FAILURE
    assert ERRNO_TO_FAILURE[1011] is FailureClass.PERMISSION_FAILURE
    assert ERRNO_TO_FAILURE[630] is FailureClass.TIMEOUT
    assert ERRNO_TO_FAILURE[604] is FailureClass.TIMEOUT
    assert ERRNO_TO_FAILURE[390114] is FailureClass.TRANSIENT_PROVIDER


def test_timeout_error_maps_to_timeout() -> None:
    assert map_error(TimeoutError("deadline")) is FailureClass.TIMEOUT
