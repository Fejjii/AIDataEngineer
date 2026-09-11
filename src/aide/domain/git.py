"""Git change classification consumed by policy rules R14–R15."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GitChangeClassification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_branch: str = Field(min_length=1)
    target_branch: str = Field(min_length=1)
    force: bool = False
    protected_branches: frozenset[str] = frozenset()
    secret_scan_hit: bool = False
