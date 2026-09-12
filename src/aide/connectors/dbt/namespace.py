"""Workflow-specific Snowflake dbt target schema.

Matches the accepted DEV namespace convention in
``aide.connectors.snowflake.namespace`` without importing that package
(avoids pulling the Snowflake vendor adapter into dbt profile rendering):

``AIDE_DEV.WF`` + first six workflow UUID hex characters + ``_DBT``.
"""

from __future__ import annotations

from uuid import UUID

DEV_DATABASE = "AIDE_DEV"
SCHEMA_SUFFIX = "DBT"
WORKFLOW_SHORT_ID_HEX_LEN = 6


def workflow_short_id(workflow_id: UUID) -> str:
    return "WF" + workflow_id.hex[:WORKFLOW_SHORT_ID_HEX_LEN].upper()


def snowflake_workflow_schema(workflow_id: UUID, *, suffix: str = SCHEMA_SUFFIX) -> str:
    """Return the unique Snowflake schema for a workflow, e.g. ``WFABC123_DBT``."""
    cleaned = suffix.strip().strip("_")
    if not cleaned:
        cleaned = SCHEMA_SUFFIX
    return f"{workflow_short_id(workflow_id)}_{cleaned}"
