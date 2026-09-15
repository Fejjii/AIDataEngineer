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
VERIFIER_FORBIDDEN = FORBIDDEN_MODULES | frozenset(
    {
        "aide.app.gateway",
        "aide.app.supervisor",
        "aide.repair.writer",
        "aide.approvals",
        "aide.orchestration",
        "aide.persistence",
        "aide.connectors.snowflake",
        "aide.connectors.dbt",
    }
)
REPAIR_FORBIDDEN = FORBIDDEN_MODULES | frozenset(
    {
        "aide.app.gateway",
        "aide.app.supervisor",
        "aide.connectors.snowflake",
        "aide.connectors.dbt",
    }
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


def test_verifier_cannot_import_gateway_connectors_or_repair_writer() -> None:
    violations: list[str] = []
    for path in _python_files(Path("src/aide/verification")):
        imported = _imported_modules(path)
        banned = {
            module
            for module in imported
            if module in VERIFIER_FORBIDDEN
            or any(
                module == banned or module.startswith(f"{banned}.") for banned in VERIFIER_FORBIDDEN
            )
        }
        if banned:
            violations.append(f"{path}: {sorted(banned)}")
        source = path.read_text(encoding="utf-8")
        assert "GovernedToolGateway" not in source
        assert "FakeSnowflakeConnector" not in source
        assert "FakeDbtConnector" not in source
    assert violations == []


def test_repair_cannot_import_gateway_or_vendor_execution() -> None:
    violations: list[str] = []
    for path in _python_files(Path("src/aide/repair")):
        imported = _imported_modules(path)
        banned = {
            module
            for module in imported
            if module in REPAIR_FORBIDDEN
            or any(
                module == banned or module.startswith(f"{banned}.") for banned in REPAIR_FORBIDDEN
            )
        }
        if banned:
            violations.append(f"{path}: {sorted(banned)}")
        source = path.read_text(encoding="utf-8")
        assert "GovernedToolGateway" not in source
    assert violations == []
