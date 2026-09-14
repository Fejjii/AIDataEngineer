"""Isolated dbtRunner entrypoint. Invoked only inside a subprocess."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def _write_result(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    result_path = os.environ.get("AIDE_DBT_RESULT_PATH")
    from dbt.cli.main import dbtRunner

    runner = dbtRunner()
    result = runner.invoke(args)
    exception = result.exception
    payload: dict[str, Any] = {
        "success": bool(result.success),
        "exception_type": type(exception).__name__ if exception is not None else None,
        "exception_module": type(exception).__module__ if exception is not None else None,
        "message": str(exception) if exception is not None else None,
    }
    _write_result(result_path, payload)
    if exception is not None and not result.success:
        return 2
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
