from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from synthetic.vantara.config import Profile, profile_config
from synthetic.vantara.export.duckdb_export import export_duckdb_fixture

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
    path.parent.mkdir(parents=True, exist_ok=True)
    config = profile_config(Profile.TINY)
    export_duckdb_fixture(
        None,  # type: ignore[arg-type]
        config,
        "v1",
        path,
        csv_dir=tiny_fixture_csv_root(),
    )
    return path


def unique_key(label: str) -> str:
    del label
    return uuid4().hex + uuid4().hex
