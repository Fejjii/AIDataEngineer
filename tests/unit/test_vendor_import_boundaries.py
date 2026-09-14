from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_MODULES = frozenset(
    {
        "aide.connectors.snowflake.real",
        "aide.connectors.snowflake.fake",
        "aide.connectors.dbt.real",
        "aide.connectors.dbt.fake",
    }
)
SCAN_ROOTS = (
    Path("src/aide/app/supervisor.py"),
    Path("src/aide/app/groups.py"),
    Path("src/aide/app/slice.py"),
    Path("src/aide/app/gateway.py"),
    Path("src/aide/orchestration"),
    Path("src/aide/generation"),
    Path("src/aide/repair"),
    Path("src/aide/verification"),
    Path("src/aide/modelling"),
    Path("src/aide/reasoning"),
    Path("src/aide/quality"),
)


def _python_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_application_and_orchestration_do_not_import_vendor_execution() -> None:
    violations: list[str] = []
    for root in SCAN_ROOTS:
        for path in _python_files(root):
            imported = _imported_modules(path)
            banned = imported.intersection(FORBIDDEN_MODULES)
            if banned:
                violations.append(f"{path}: {sorted(banned)}")
    assert violations == []
