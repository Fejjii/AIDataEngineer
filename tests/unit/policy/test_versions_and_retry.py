from __future__ import annotations

from uuid import uuid4

from aide.capabilities.registry import CapabilityRegistry
from aide.capabilities.v1_kernel import kernel_registry
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.v1_instances import SNOWFLAKE_RO
from aide.domain.effects import EffectSemantics
from aide.domain.failures import FailureClass
from aide.domain.states import DispatchState
from aide.domain.versions import CapabilityContractRef, ContractSnapshot
from aide.policy.reasons import REASON_CLASS, DenyClass, ReasonCode
from aide.policy.retry import RetryDecision, decide_after_failure, decide_after_reconcile
from aide.policy.versions import emit_contract_version_unavailable, map_unavailable_reason


def test_missing_pinned_version_emits_environmental_reason() -> None:
    capabilities = kernel_registry()
    connectors = ConnectorRegistry()
    connectors.register(SNOWFLAKE_RO, capabilities.required_permissions())
    snapshot = ContractSnapshot(
        snapshot_id=uuid4(),
        capability_contracts=(
            CapabilityContractRef(
                capability_id="execute_query",
                capability_contract_version=99,
                input_schema_version=1,
                output_schema_version=1,
            ),
        ),
        connector_versions={"snowflake_ro": "1.0.0"},
    )
    reason = emit_contract_version_unavailable(
        snapshot, capabilities=capabilities, connectors=connectors
    )
    assert reason is ReasonCode.CONTRACT_VERSION_UNAVAILABLE
    assert reason.value != ReasonCode.UNKNOWN_TARGET.value
    assert map_unavailable_reason(reason) is DenyClass.ENVIRONMENTAL
    assert REASON_CLASS[ReasonCode.CONTRACT_VERSION_UNAVAILABLE] is DenyClass.ENVIRONMENTAL

    present = ContractSnapshot(
        snapshot_id=uuid4(),
        capability_contracts=(
            CapabilityContractRef(
                capability_id="execute_query",
                capability_contract_version=1,
                input_schema_version=1,
                output_schema_version=1,
            ),
        ),
        connector_versions={"snowflake_ro": "1.0.0"},
    )
    assert (
        emit_contract_version_unavailable(present, capabilities=capabilities, connectors=connectors)
        is None
    )


def test_capability_version_compatibility() -> None:
    from aide.connectors.base.spec import versions_compatible

    impl = next(
        item for item in SNOWFLAKE_RO.implementations if item.capability_id == "execute_query"
    )
    assert versions_compatible(
        impl, contract_version=1, input_schema_version=1, output_schema_version=1
    )
    assert not versions_compatible(
        impl, contract_version=2, input_schema_version=1, output_schema_version=1
    )


def test_exact_max_attempts_and_side_effect_retry_rules() -> None:
    assert (
        decide_after_failure(
            effect_semantics=EffectSemantics.NON_IDEMPOTENT,
            dispatch_state=DispatchState.DISPATCHED,
            failure_class=FailureClass.CONNECTOR_FAILURE,
            attempt_count=1,
            max_attempts=3,
        )
        is RetryDecision.RECONCILE_FIRST
    )
    assert (
        decide_after_failure(
            effect_semantics=EffectSemantics.NON_IDEMPOTENT,
            dispatch_state=DispatchState.OUTCOME_AMBIGUOUS,
            failure_class=FailureClass.TIMEOUT,
            attempt_count=1,
            max_attempts=3,
        )
        is RetryDecision.RECONCILE_FIRST
    )
    assert (
        decide_after_failure(
            effect_semantics=EffectSemantics.NON_IDEMPOTENT,
            dispatch_state=DispatchState.NOT_DISPATCHED,
            failure_class=FailureClass.CONNECTOR_FAILURE,
            attempt_count=1,
            max_attempts=3,
        )
        is RetryDecision.RETRY
    )
    assert (
        decide_after_reconcile(NoEffect(evidence="absent"), attempt_count=1, max_attempts=3)
        is RetryDecision.RETRY
    )
    assert (
        decide_after_reconcile(NoEffect(evidence="absent"), attempt_count=1, max_attempts=1)
        is RetryDecision.FAILED
    )
    assert (
        decide_after_reconcile(NoEffect(evidence="absent"), attempt_count=3, max_attempts=3)
        is RetryDecision.FAILED
    )
    assert (
        decide_after_reconcile(
            Unknown(reason="lag", evidence=None), attempt_count=1, max_attempts=3
        )
        is RetryDecision.PARK
    )
    assert (
        decide_after_reconcile(
            InProgress(external_ref="q1", retry_after_seconds=5),
            attempt_count=1,
            max_attempts=3,
        )
        is RetryDecision.WAIT_IN_PROGRESS
    )
    assert (
        decide_after_reconcile(EffectFound(output={"ok": True}), attempt_count=1, max_attempts=3)
        is RetryDecision.SUCCEEDED
    )
    assert (
        decide_after_failure(
            effect_semantics=EffectSemantics.SIDE_EFFECT_FREE,
            dispatch_state=DispatchState.DISPATCHED,
            failure_class=FailureClass.TRANSIENT_PROVIDER,
            attempt_count=1,
            max_attempts=2,
        )
        is RetryDecision.RETRY
    )
    _ = CapabilityRegistry
