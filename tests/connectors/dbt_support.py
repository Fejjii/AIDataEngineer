from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import duckdb

from aide.connectors.base.context import RecoveryContext
from aide.connectors.dbt.workspace import tiny_fixture_csv_root
from aide.domain.enums import TargetEnv
from aide.domain.versions import CapabilityContractRef


def recovery_for(
    context: object,
    capability_id: str,
    *,
    locator: dict[str, str] | None = None,
) -> RecoveryContext:
    from aide.connectors.base.context import CallContext

    assert isinstance(context, CallContext)
    return RecoveryContext(
        workflow_id=context.workflow_id,
        phase_run_id=context.phase_run_id,
        task_id=context.task_id,
        operation_idempotency_key=context.operation_idempotency_key,
        resolved_input_digest=context.resolved_input_digest,
        resolved_input_schema_version=1,
        capability=CapabilityContractRef(
            capability_id=capability_id,
            capability_contract_version=1,
            input_schema_version=1,
            output_schema_version=1,
        ),
        connector_id="dbt_dev",
        connector_version="1.0.0",
        target_environment=TargetEnv.DEV,
        attempts=(),
        operation_locator=locator or {},
        reconcile_deadline=datetime.now(UTC) + timedelta(seconds=30),
    )


def build_tiny_v1_duckdb(path: Path) -> Path:
    """Build a DuckDB 1.5-compatible tiny v1 file from committed CSVs.

    DuckDB 1.5 treats ``a.b`` as catalog.schema. Connecting to a file named
    ``vantara_raw.duckdb`` yields catalog ``vantara_raw``, which quoted
    ``"VANTARA_RAW"`` identifiers resolve to. The DE004 nested-schema export
    helper is not used here (it targets an older catalog layout).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    csv_root = tiny_fixture_csv_root()
    conn = duckdb.connect(str(path))
    try:
        conn.execute("CREATE SCHEMA IF NOT EXISTS BILLING")
        conn.execute(
            "CREATE TABLE BILLING.CUSTOMERS AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)",
            [str(csv_root / "billing" / "customers.csv")],
        )
        conn.execute(
            "CREATE TABLE BILLING.INVOICES AS SELECT * FROM read_csv_auto(?, HEADER=TRUE)",
            [str(csv_root / "billing" / "invoices.csv")],
        )
    finally:
        conn.close()
    return path


def unique_key(label: str) -> str:
    del label
    return uuid4().hex + uuid4().hex
