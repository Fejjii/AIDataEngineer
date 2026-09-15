"""Internal snapshot used while assembling benchmark records."""

from __future__ import annotations

from dataclasses import dataclass, field

from aide.domain.verification import VerifierVerdict


@dataclass
class RunSnapshot:
    parse_ok: bool
    compile_ok: bool
    execute_ok: bool
    tests_ok: bool
    quality_outcome: bool
    reconciliation_outcome: bool
    fail_reason: str | None
    block_reason: str | None
    repair_class: str | None
    from_column: str | None
    to_column: str | None
    repair_count: int
    repair_allowed: bool
    verifier_verdict: VerifierVerdict | None
    human_intervention_count: int
    retry_count: int
    wall_clock_duration_ms: int
    repair_duration_ms: int
    evidence_completeness_pct: int
    asset_selection: tuple[tuple[str, ...], ...]
    model_names: tuple[str, ...]
    governed_tool_operations: int
    policy_evaluations: int
    tests_executed: int
    quality_checks_executed: int
    extra: dict[str, object] = field(default_factory=dict)
