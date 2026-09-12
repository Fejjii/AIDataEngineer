"""V1 Snowflake instance advertisements. Not vendor connectors."""

from __future__ import annotations

from aide.connectors.base.spec import (
    CapabilityImplementation,
    ConnectorKind,
    ConnectorSpec,
    IdentityClass,
    ObjectAllowList,
)
from aide.domain.enums import TargetEnv
from aide.domain.permissions import PermissionLevel

_READ_CAPABILITIES = (
    "discover_assets",
    "describe_asset",
    "detect_schema_drift",
    "profile_dataset",
    "sample_dataset",
    "infer_relationships",
    "validate_query",
    "execute_query",
    "evaluate_execution_policy",
    "get_execution_metrics",
    "get_cost_metrics",
)

_WRITE_CAPABILITIES = ("create_dataset", "drop_dataset")


def _impl(capability_id: str) -> CapabilityImplementation:
    return CapabilityImplementation(
        capability_id=capability_id,
        supported_contract_versions=frozenset({1}),
        input_schema_versions=frozenset({1}),
        output_schema_versions=frozenset({1}),
    )


SNOWFLAKE_RO = ConnectorSpec(
    connector_id="snowflake_ro",
    kind=ConnectorKind.WAREHOUSE,
    vendor="snowflake",
    version="1.0.0",
    target_environment=TargetEnv.DEV,
    identity_class=IdentityClass.READ_ONLY,
    implementations=frozenset(_impl(cid) for cid in _READ_CAPABILITIES),
    allowed_permissions=frozenset({PermissionLevel.READ}),
    allow_list=ObjectAllowList(databases=frozenset({"RAW", "AIDE_DEV"})),
    dialect="snowflake",
    is_fake=False,
)

SNOWFLAKE_DEV = ConnectorSpec(
    connector_id="snowflake_dev",
    kind=ConnectorKind.WAREHOUSE,
    vendor="snowflake",
    version="1.0.0",
    target_environment=TargetEnv.DEV,
    identity_class=IdentityClass.DEVELOPMENT,
    implementations=frozenset(_impl(cid) for cid in _WRITE_CAPABILITIES),
    allowed_permissions=frozenset({PermissionLevel.DEVELOPMENT_WRITE, PermissionLevel.DESTRUCTIVE}),
    allow_list=ObjectAllowList(databases=frozenset({"AIDE_DEV"})),
    dialect="snowflake",
    is_fake=False,
)
