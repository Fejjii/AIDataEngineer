"""Stable connector protocol and advertisements."""

from aide.connectors.base.context import (
    AttemptRecoveryRef,
    CallContext,
    RecoveryContext,
    RedactionPolicy,
)
from aide.connectors.base.health import ConnectorHealthSnapshot, HealthStatus
from aide.connectors.base.protocol import Connector
from aide.connectors.base.reconcile import (
    EffectFound,
    InProgress,
    NoEffect,
    ReconcileResult,
    Unknown,
)
from aide.connectors.base.registry import (
    ConnectorRegistry,
    DuplicateConnectorError,
    UnknownConnectorError,
    startup_permission_check,
)
from aide.connectors.base.spec import (
    CapabilityImplementation,
    ConnectorKind,
    ConnectorSpec,
    IdentityClass,
    ObjectAllowList,
    versions_compatible,
)
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO

__all__ = [
    "SNOWFLAKE_DEV",
    "SNOWFLAKE_RO",
    "AttemptRecoveryRef",
    "CallContext",
    "CapabilityImplementation",
    "Connector",
    "ConnectorHealthSnapshot",
    "ConnectorKind",
    "ConnectorRegistry",
    "ConnectorSpec",
    "DuplicateConnectorError",
    "EffectFound",
    "HealthStatus",
    "IdentityClass",
    "InProgress",
    "NoEffect",
    "ObjectAllowList",
    "RecoveryContext",
    "ReconcileResult",
    "RedactionPolicy",
    "Unknown",
    "UnknownConnectorError",
    "startup_permission_check",
    "versions_compatible",
]
