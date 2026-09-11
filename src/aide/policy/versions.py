"""CONTRACT_VERSION_UNAVAILABLE emission predicate and ENVIRONMENTAL mapping."""

from __future__ import annotations

from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import versions_compatible
from aide.domain.versions import ContractSnapshot
from aide.policy.reasons import REASON_CLASS, DenyClass, ReasonCode


def emit_contract_version_unavailable(
    snapshot: ContractSnapshot,
    *,
    capabilities: CapabilityRegistry,
    connectors: ConnectorRegistry,
) -> ReasonCode | None:
    """Scheduler/materialization predicate. Distinct from R1 UNKNOWN_TARGET."""
    for contract in snapshot.capability_contracts:
        if not capabilities.contains(contract.capability_id, contract.capability_contract_version):
            return ReasonCode.CONTRACT_VERSION_UNAVAILABLE
    for connector_id, pinned_version in snapshot.connector_versions.items():
        if not connectors.contains(connector_id):
            return ReasonCode.CONTRACT_VERSION_UNAVAILABLE
        spec = connectors.get(connector_id)
        if spec.version != pinned_version:
            return ReasonCode.CONTRACT_VERSION_UNAVAILABLE
        for contract in snapshot.capability_contracts:
            impl = spec.implementation(contract.capability_id)
            if impl is None:
                continue
            if not versions_compatible(
                impl,
                contract_version=contract.capability_contract_version,
                input_schema_version=contract.input_schema_version,
                output_schema_version=contract.output_schema_version,
            ):
                return ReasonCode.CONTRACT_VERSION_UNAVAILABLE
    return None


def map_unavailable_reason(reason: ReasonCode) -> DenyClass:
    if reason is not ReasonCode.CONTRACT_VERSION_UNAVAILABLE:
        raise ValueError("not a contract-version reason")
    deny_class = REASON_CLASS[reason]
    if deny_class is not DenyClass.ENVIRONMENTAL:
        raise ValueError("CONTRACT_VERSION_UNAVAILABLE must map to ENVIRONMENTAL")
    return deny_class
