"""Known Interview MVP limitations remain explicit and out of scope."""

from __future__ import annotations

from pathlib import Path

from aide.domain.permissions import DISABLED_V1, PermissionLevel
from aide.domain.repair import ACCEPTED_FROM_COLUMN, ACCEPTED_TO_COLUMN
from aide.domain.roadmap import DEFERRED_AFTER_MVP004


def test_e_lim_01_known_limitations_are_documented() -> None:
    demo = Path("docs/INTERVIEW_DEMO.md").read_text(encoding="utf-8")
    boundary = Path("docs/pivot/PIVOT001_CONTRACT_BOUNDARY.md").read_text(encoding="utf-8")
    combined = demo + "\n" + boundary
    assert "GitHub" in combined or "github" in combined.lower()
    assert "INVOICE_STATUS" in combined
    assert ACCEPTED_FROM_COLUMN == "INVOICE_STATUS"
    assert ACCEPTED_TO_COLUMN == "STATUS"
    assert PermissionLevel.PRODUCTION_WRITE in DISABLED_V1
    assert PermissionLevel.SECURITY in DISABLED_V1
    assert "DE015" in DEFERRED_AFTER_MVP004
    assert "DE012" in DEFERRED_AFTER_MVP004
    assert "second automated repair class" in boundary.lower()
    assert "tiny" in boundary.lower()
