"""Canonical Snowflake QUERY_TAG serializer and parser."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from aide.connectors.base.context import CallContext

QUERY_TAG_VERSION = "aide:v1"
MANDATORY_KEYS: tuple[str, ...] = ("wf", "phase_run", "task", "op", "attempt", "n")


class QueryTag(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow_id: UUID
    phase_run_id: UUID
    task_id: UUID
    operation_idempotency_key: str = Field(min_length=64, max_length=64)
    attempt_id: UUID
    attempt_number: int = Field(ge=1)


class QueryTagError(ValueError):
    pass


def format_query_tag(context: CallContext) -> str:
    """Serialize complete operation and attempt identity. Never truncates the op key."""
    return (
        f"{QUERY_TAG_VERSION};wf={context.workflow_id};phase_run={context.phase_run_id};"
        f"task={context.task_id};op={context.operation_idempotency_key};"
        f"attempt={context.attempt_id};n={context.attempt_number}"
    )


def parse_query_tag(raw: str) -> QueryTag:
    text = raw.strip()
    if not text.startswith(f"{QUERY_TAG_VERSION};"):
        raise QueryTagError("query tag must start with aide:v1")
    body = text[len(QUERY_TAG_VERSION) + 1 :]
    pairs: dict[str, str] = {}
    for part in body.split(";"):
        if not part:
            continue
        if "=" not in part:
            raise QueryTagError("malformed query tag pair")
        key, value = part.split("=", 1)
        if key in pairs:
            raise QueryTagError(f"duplicate query tag key {key}")
        pairs[key] = value
    extra = set(pairs) - set(MANDATORY_KEYS)
    missing = set(MANDATORY_KEYS) - set(pairs)
    if extra:
        raise QueryTagError(f"unknown query tag keys: {sorted(extra)}")
    if missing:
        raise QueryTagError(f"missing query tag keys: {sorted(missing)}")
    op_key = pairs["op"]
    if len(op_key) != 64:
        raise QueryTagError("operation key must be complete 64-hex digest")
    try:
        attempt_number = int(pairs["n"])
    except ValueError as exc:
        raise QueryTagError("attempt number must be an integer") from exc
    return QueryTag(
        workflow_id=UUID(pairs["wf"]),
        phase_run_id=UUID(pairs["phase_run"]),
        task_id=UUID(pairs["task"]),
        operation_idempotency_key=op_key,
        attempt_id=UUID(pairs["attempt"]),
        attempt_number=attempt_number,
    )


def query_tag_from_context(context: CallContext) -> QueryTag:
    return parse_query_tag(format_query_tag(context))
