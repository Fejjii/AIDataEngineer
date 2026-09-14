"""Append-only dbt invocation journal. Side-effecting runs are NON_IDEMPOTENT."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.effects import EffectSemantics


class DispatchStatus(str, Enum):
    NOT_DISPATCHED = "NOT_DISPATCHED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    TERMINATED = "TERMINATED"
    IN_PROGRESS = "IN_PROGRESS"


class InvocationJournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID
    operation: str
    attempt_id: UUID
    attempt_number: int
    operation_idempotency_key: str
    selected_nodes: tuple[str, ...]
    compiled_configuration: dict[str, Any]
    dispatch_status: DispatchStatus
    adapter_response: dict[str, Any] | None = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    effect_semantics: EffectSemantics = EffectSemantics.NON_IDEMPOTENT
    effect_applied: bool = False
    recorded_at: str


def journal_path(invocation_dir: Path) -> Path:
    return invocation_dir / "journal.jsonl"


def append_journal(invocation_dir: Path, entry: InvocationJournalEntry) -> Path:
    invocation_dir.mkdir(parents=True, exist_ok=True)
    path = journal_path(invocation_dir)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry.model_dump_json() + "\n")
    return path


def read_journal(invocation_dir: Path) -> tuple[InvocationJournalEntry, ...]:
    path = journal_path(invocation_dir)
    if not path.exists():
        return ()
    entries: list[InvocationJournalEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(InvocationJournalEntry.model_validate_json(line))
    return tuple(entries)


def latest_journal(invocation_dir: Path) -> InvocationJournalEntry | None:
    entries = read_journal(invocation_dir)
    return entries[-1] if entries else None


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def find_latest_journal_for_operation(
    work_invocations: Path, operation_idempotency_key: str
) -> tuple[Path, InvocationJournalEntry] | None:
    op_dir = work_invocations / operation_idempotency_key
    if not op_dir.exists():
        return None
    latest: tuple[Path, InvocationJournalEntry] | None = None
    for attempt_dir in sorted(op_dir.iterdir()):
        if not attempt_dir.is_dir():
            continue
        entry = latest_journal(attempt_dir)
        if entry is None:
            continue
        latest = (attempt_dir, entry)
    return latest
