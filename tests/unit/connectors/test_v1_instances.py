from __future__ import annotations

from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.registry import ConnectorRegistry, startup_permission_check
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.domain.permissions import PermissionLevel


def test_snowflake_ro_is_valid_read_binding() -> None:
    assert SNOWFLAKE_RO.identity_class.value == "READ_ONLY"
    assert PermissionLevel.READ in SNOWFLAKE_RO.allowed_permissions
    assert SNOWFLAKE_RO.advertises("execute_query", 1)
    startup_permission_check(SNOWFLAKE_RO, kernel_registry().required_permissions())


def test_snowflake_dev_cannot_satisfy_read() -> None:
    assert PermissionLevel.READ not in SNOWFLAKE_DEV.allowed_permissions
    assert SNOWFLAKE_DEV.identity_class.value == "DEVELOPMENT"
    assert not SNOWFLAKE_DEV.advertises("execute_query")
    assert SNOWFLAKE_DEV.advertises("create_dataset", 1)
    startup_permission_check(SNOWFLAKE_DEV, kernel_registry().required_permissions())


def test_connector_registry_registers_v1_instances() -> None:
    registry = ConnectorRegistry()
    capabilities = kernel_registry()
    registry.register(SNOWFLAKE_RO, capabilities.required_permissions())
    registry.register(SNOWFLAKE_DEV, capabilities.required_permissions())
    assert registry.contains("snowflake_ro")
    assert registry.contains("snowflake_dev")
