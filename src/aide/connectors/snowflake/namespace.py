"""Workflow-specific DEV namespace contract: AIDE_DEV.<WORKFLOW_SHORT_ID>_*.

Architecture: docs/CONNECTOR_ARCHITECTURE.md §5.1 and docs/DEMO_COMPANY.md §7.
"""

from __future__ import annotations

from uuid import UUID

from aide.connectors.snowflake.dialect import normalize_identifier
from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetRef

DEV_DATABASE = "AIDE_DEV"
WORKFLOW_SHORT_ID_HEX_LEN = 6


def workflow_short_id(workflow_id: UUID) -> str:
    return "WF" + workflow_id.hex[:WORKFLOW_SHORT_ID_HEX_LEN].upper()


def schema_matches_workflow(schema: str, workflow_id: UUID) -> bool:
    prefix = workflow_short_id(workflow_id) + "_"
    return normalize_identifier(schema).startswith(prefix)


def is_dev_namespace_asset(asset: AssetRef, workflow_id: UUID) -> bool:
    address = tuple(normalize_identifier(part) for part in asset.address)
    if len(address) < 2:
        return False
    return address[0] == DEV_DATABASE and schema_matches_workflow(address[1], workflow_id)


def require_dev_namespace(asset: AssetRef, workflow_id: UUID) -> None:
    if not is_dev_namespace_asset(asset, workflow_id):
        raise SnowflakeMappedError(
            FailureClass.UNSAFE_OPERATION,
            "DEV write target is outside the workflow namespace",
        )


def provenance_comment(*, workflow_id: UUID, operation_idempotency_key: str) -> str:
    return f"aide:v1;wf={workflow_id};op={operation_idempotency_key}"
