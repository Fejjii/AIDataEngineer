"""V1 dbt connector advertisements."""

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

DBT_CAPABILITIES: tuple[str, ...] = (
    "create_transformation",
    "compile_transformation",
    "execute_transformation",
    "run_pipeline",
    "run_tests",
    "get_lineage",
)

DBT_REQUIRED_PERMISSIONS: dict[str, PermissionLevel] = {
    "create_transformation": PermissionLevel.DEVELOPMENT_WRITE,
    "compile_transformation": PermissionLevel.DEVELOPMENT_EXECUTE,
    "execute_transformation": PermissionLevel.DEVELOPMENT_EXECUTE,
    "run_pipeline": PermissionLevel.DEVELOPMENT_EXECUTE,
    "run_tests": PermissionLevel.DEVELOPMENT_EXECUTE,
    "get_lineage": PermissionLevel.READ,
}


def _impl(capability_id: str) -> CapabilityImplementation:
    return CapabilityImplementation(
        capability_id=capability_id,
        supported_contract_versions=frozenset({1}),
        input_schema_versions=frozenset({1}),
        output_schema_versions=frozenset({1}),
    )


DBT_DEV = ConnectorSpec(
    connector_id="dbt_dev",
    kind=ConnectorKind.TRANSFORMATION,
    vendor="dbt",
    version="1.0.0",
    target_environment=TargetEnv.DEV,
    identity_class=IdentityClass.DEVELOPMENT,
    implementations=frozenset(_impl(cid) for cid in DBT_CAPABILITIES),
    allowed_permissions=frozenset(
        {
            PermissionLevel.READ,
            PermissionLevel.DEVELOPMENT_EXECUTE,
            PermissionLevel.DEVELOPMENT_WRITE,
        }
    ),
    allow_list=ObjectAllowList(databases=frozenset({"VANTARA_RAW", "AIDE_DEV"})),
    dialect="snowflake",
    is_fake=False,
)

FAKE_DBT_DEV = DBT_DEV.model_copy(update={"is_fake": True})

# ``deploy_staging`` / ``dbt_staging`` is owned by DE017. Do not advertise it
# until a real handler exists. Connector advertisements must match handlers.
