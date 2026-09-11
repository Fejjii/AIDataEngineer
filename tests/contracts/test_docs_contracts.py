from __future__ import annotations

import subprocess
from pathlib import Path

from aide.domain.permissions import PermissionLevel
from aide.policy.reasons import REASON_CLASS, ReasonCode

ROOT = Path(__file__).resolve().parents[2]


def test_architecture_is_accepted() -> None:
    text = (ROOT / ".ai" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "**ACCEPTED**" in text
    plan = (ROOT / "docs" / "IMPLEMENTATION_PLAN.md").read_text(encoding="utf-8")
    assert "### 5.1 DE 002A" in plan or "## 5.1 DE 002A" in plan


def test_every_reason_code_is_classified_and_documented() -> None:
    permission_doc = (ROOT / "docs" / "PERMISSION_MODEL.md").read_text(encoding="utf-8")
    assert set(REASON_CLASS) == set(ReasonCode)
    for code in ReasonCode:
        assert code.value in permission_doc, code.value
        assert code in REASON_CLASS


def test_every_permission_is_documented() -> None:
    permission_doc = (ROOT / "docs" / "PERMISSION_MODEL.md").read_text(encoding="utf-8")
    for grant in PermissionLevel:
        assert f"`{grant.value}`" in permission_doc or grant.value in permission_doc


def test_required_architecture_docs_exist() -> None:
    required = [
        "docs/ARCHITECTURE.md",
        "docs/STATE_MODEL.md",
        "docs/CAPABILITY_MODEL.md",
        "docs/TOOL_CONTRACTS.md",
        "docs/PERMISSION_MODEL.md",
        "docs/CONNECTOR_ARCHITECTURE.md",
        "docs/TECH_STACK.md",
        "docs/IMPLEMENTATION_PLAN.md",
        "docs/agent/CLOUD_HANDOFF.md",
    ]
    for rel in required:
        assert (ROOT / rel).is_file(), rel


def test_aide_secrets_package_is_tracked() -> None:
    """Regression: a root `secrets/` gitignore must not hide aide.secrets."""
    path = ROOT / "src" / "aide" / "secrets" / "__init__.py"
    assert path.is_file()
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(ROOT))],
        cwd=ROOT,
        check=False,
    )
    assert ignored.returncode == 1
