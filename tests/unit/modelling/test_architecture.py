from __future__ import annotations

from tests.unit.modelling.factories import vantara_decision

from aide.domain.identity import compute_resolved_input_digest


def test_vantara_demo_matches_strategy_section_6() -> None:
    decision = vantara_decision()
    assert decision.layering.decision == "STAGING_INTERMEDIATE_MARTS"
    assert decision.layering.rule == "L1"
    assert decision.naming == "DBT_DEFAULT"
    assert decision.integration_layer.decision == "NO_VAULT"
    assert decision.integration_layer.rule == "V3"
    assert decision.presentation.decision == "STAR_SCHEMA"
    assert decision.presentation.rule == "P1"
    assert decision.approval_required is False
    assert decision.signals.deliverable_type == "ANALYTICAL_DATA_PRODUCT"
    assert decision.signals.history_requirements == "FULL_HISTORY"
    assert decision.signals.auditability == "LOW"
    assert decision.signals.source_system_count == 4
    assert decision.signals.volume_class == "M"
    assert decision.signals.downstream_consumers == ("BI",)
    assert decision.signals.latency_requirement == "DAILY"
    assert decision.signals.key_quality == "DUPLICATES_PRESENT"
    assert decision.signals.identifier_alignment == "PARTIAL"
    customer = next(item for item in decision.dimensions if item.entity == "customer")
    plan = next(item for item in decision.dimensions if item.entity == "plan")
    date_dim = next(item for item in decision.dimensions if item.entity == "date")
    assert customer.history == "SCD2"
    assert customer.source_history is False
    assert customer.strategy == "snapshot_timestamp"
    assert "D1" in customer.rule and "D7" in customer.rule
    assert plan.history == "SCD2"
    assert plan.source_history is True
    assert plan.strategy == "source_validity_intervals"
    assert "D1" in plan.rule and "D6" in plan.rule
    assert date_dim.history == "STATIC" and "D8" in date_dim.rule
    invoice = next(item for item in decision.facts if item.entity == "invoice_line")
    payment = next(item for item in decision.facts if item.entity == "payment")
    snapshot = next(item for item in decision.facts if item.kind == "PERIODIC_SNAPSHOT_FACT")
    assert invoice.kind == "TRANSACTION_FACT"
    assert "F1" in invoice.rule
    assert "M3" in invoice.rule
    assert invoice.materialization == "incremental"
    assert payment.kind == "TRANSACTION_FACT"
    assert "F4" in payment.rule
    assert payment.dedup_required is True
    assert snapshot.kind == "PERIODIC_SNAPSHOT_FACT"
    assert "F2" in snapshot.rule
    assert any(item.entity == "customer" for item in decision.dedup)
    assert any(item.entity == "payment" for item in decision.dedup)
    expected = (
        "L1",
        "V3",
        "P1",
        "F1",
        "F2",
        "F4",
        "D1",
        "D6",
        "D7",
        "D8",
        "M1",
        "M2",
        "M3",
        "M6",
    )
    for rule in expected:
        assert rule in decision.rule_ids
    assert decision.rule_ids == tuple(sorted(decision.rule_ids, key=_rule_key))


def _rule_key(rule_id: str) -> tuple[int, int]:
    family = {"L": 0, "V": 1, "P": 2, "F": 3, "D": 4, "M": 5}[rule_id[0]]
    return family, int(rule_id[1:])


def test_rule_ids_are_rendered() -> None:
    decision = vantara_decision()
    dumped = decision.model_dump(mode="json")
    assert dumped["rule_ids"]
    assert dumped["presentation"]["rule"] == "P1"
    assert dumped["integration_layer"]["rule"] == "V3"


def test_architecture_decision_serializes() -> None:
    decision = vantara_decision()
    restored = decision.__class__.model_validate(decision.model_dump(mode="json"))
    assert restored == decision
    assert len(compute_resolved_input_digest(decision)) == 64


def test_data_vault_recommendation_sets_approval() -> None:
    from tests.unit.modelling.factories import make_signals

    decision = vantara_decision(
        signals=make_signals(
            auditability="HIGH",
            source_system_count=4,
            history_requirements="FULL_HISTORY",
            change_frequency="HIGH",
        )
    )
    assert decision.integration_layer.rule == "V1"
    assert decision.approval_required is True
    assert decision.presentation.decision == "STAR_SCHEMA"


def test_large_volume_alone_does_not_set_cost_class_approval() -> None:
    from tests.unit.modelling.factories import make_signals

    decision = vantara_decision(signals=make_signals(volume_class="XL"))
    assert decision.signals.volume_class == "XL"
    assert decision.estimated_cost_class == "UNKNOWN"
    assert "cost_class" not in decision.approval_reasons
    assert decision.approval_required is False


def test_explicit_warehouse_cost_class_requires_approval() -> None:
    from aide.modelling.vantara import vantara_modelling_context

    ctx = vantara_modelling_context().model_copy(update={"estimated_warehouse_cost_class": "L"})
    decision = vantara_decision(context=ctx)
    assert decision.estimated_cost_class == "L"
    assert decision.signals.volume_class == "M"
    assert decision.approval_required is True
    assert "cost_class" in decision.approval_reasons


def test_medallion_naming_keeps_canonical_structure() -> None:
    from aide.modelling.context import OrgModellingConfig
    from aide.modelling.vantara import vantara_modelling_context

    ctx = vantara_modelling_context().model_copy(
        update={"org": OrgModellingConfig(auditability="LOW", naming_convention="MEDALLION")}
    )
    decision = vantara_decision(context=ctx)
    assert decision.naming == "MEDALLION"
    assert decision.layering.decision == "STAGING_INTERMEDIATE_MARTS"
