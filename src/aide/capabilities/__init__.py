"""Capability contracts and in-memory registry."""

from aide.capabilities.registry import (
    CapabilityRegistry,
    DuplicateCapabilityError,
    UnknownCapabilityError,
)
from aide.capabilities.spec import (
    AuditSpec,
    CapabilityId,
    CapabilityKind,
    CapabilitySpec,
    ConnectorRequirement,
    CostClass,
    RetryPolicy,
)

__all__ = [
    "AuditSpec",
    "CapabilityId",
    "CapabilityKind",
    "CapabilityRegistry",
    "CapabilitySpec",
    "ConnectorRequirement",
    "CostClass",
    "DuplicateCapabilityError",
    "RetryPolicy",
    "UnknownCapabilityError",
]
