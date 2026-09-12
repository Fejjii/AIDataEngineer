from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aide.connectors.base.context import CallContext, RedactionPolicy
from aide.connectors.snowflake.query_tags import format_query_tag, parse_query_tag


def test_query_tag_round_trip_preserves_operation_and_attempt() -> None:
    context = CallContext(
        workflow_id=uuid4(),
        phase_run_id=uuid4(),
        task_id=uuid4(),
        operation_idempotency_key="a" * 64,
        resolved_input_digest="b" * 64,
        contract_snapshot_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=3,
        claim_epoch=1,
        cancellation_epoch=0,
        deadline=datetime.now(UTC) + timedelta(seconds=5),
        external_correlation="corr",
        redaction=RedactionPolicy(),
    )
    tag = format_query_tag(context)
    parsed = parse_query_tag(tag)
    assert parsed.operation_idempotency_key == context.operation_idempotency_key
    assert parsed.attempt_id == context.attempt_id
    assert parsed.attempt_number == 3
    assert "op=" + context.operation_idempotency_key in tag
