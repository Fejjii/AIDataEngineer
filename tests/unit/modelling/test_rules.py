from __future__ import annotations

from tests.unit.modelling.factories import (
    asset,
    make_profile,
    make_signals,
    vantara_duplicates,
    vantara_profiles,
)

from aide.capabilities.io import (
    ArchitectureDecision,
    AssetProfileEvidence,
    DuplicateEvidenceLite,
    ModellingSignals,
    RequirementSpec,
)
from aide.domain.sql import AssetRef
from aide.modelling.context import DimensionHierarchyHint, ModellingContext
from aide.modelling.engine import ModellingDecisionEngine
from aide.modelling.platform import SNOWFLAKE_CAPABILITIES
from aide.modelling.vantara import vantara_demo_requirement

ENGINE = ModellingDecisionEngine()


def _decide(
    signals: ModellingSignals,
    *,
    selected: tuple[AssetRef, ...] | None = None,
    profiles: tuple[AssetProfileEvidence, ...] | None = None,
    duplicates: tuple[DuplicateEvidenceLite, ...] = (),
    context: ModellingContext | None = None,
    requirement: RequirementSpec | None = None,
) -> ArchitectureDecision:
    return ENGINE.decide(
        requirement or vantara_demo_requirement(),
        selected=selected or (),
        profiles=profiles or (),
        duplicates=duplicates,
        context=context,
        signals=signals,
    )


def test_l1_analytical_product() -> None:
    decision = _decide(make_signals())
    assert decision.layering.rule == "L1"
    assert decision.layering.decision == "STAGING_INTERMEDIATE_MARTS"


def test_l2_model_change() -> None:
    signals = make_signals(deliverable_type="MODEL_CHANGE")
    ctx = ModellingContext(existing_layering="STAGING_INTERMEDIATE_MARTS")
    decision = _decide(signals, context=ctx)
    assert decision.layering.rule == "L2"
    assert decision.layering.decision == "REUSE_EXISTING"


def test_l2_without_existing_layering_is_blocking() -> None:
    signals = make_signals(deliverable_type="MODEL_CHANGE")
    decision = _decide(signals, context=ModellingContext())
    assert decision.layering.rule == "L2"
    assert any(item.rule == "L2" and item.blocking for item in decision.open_questions)


def test_l3_quality_suite() -> None:
    decision = _decide(make_signals(deliverable_type="QUALITY_SUITE"))
    assert decision.layering.rule == "L3"
    assert decision.layering.decision == "TESTS_ONLY"


def test_l4_investigation() -> None:
    decision = _decide(make_signals(deliverable_type="INVESTIGATION"))
    assert decision.layering.rule == "L4"
    assert decision.layering.decision == "EPHEMERAL_QUERIES"


def test_v1_raw_vault_recommended_requires_approval() -> None:
    signals = make_signals(
        auditability="HIGH",
        source_system_count=3,
        history_requirements="FULL_HISTORY",
        change_frequency="MEDIUM",
    )
    decision = _decide(signals)
    assert decision.integration_layer.rule == "V1"
    assert decision.integration_layer.decision == "RAW_VAULT_RECOMMENDED"
    assert decision.approval_required is True
    assert "V1" in decision.approval_reasons


def test_v2_misaligned_many_systems() -> None:
    signals = make_signals(
        auditability="LOW",
        source_system_count=5,
        identifier_alignment="MISALIGNED",
        change_frequency="LOW",
    )
    decision = _decide(signals)
    assert decision.integration_layer.rule == "V2"
    assert decision.approval_required is True
    assert "V2" in decision.approval_reasons


def test_v3_otherwise_no_vault() -> None:
    decision = _decide(make_signals())
    assert decision.integration_layer.rule == "V3"
    assert decision.integration_layer.decision == "NO_VAULT"
    assert decision.approval_required is False


def test_p1_star_schema_for_bi() -> None:
    decision = _decide(make_signals())
    assert decision.presentation.rule == "P1"
    assert decision.presentation.decision == "STAR_SCHEMA"


def test_p2_wide_feature_table() -> None:
    signals = make_signals(
        downstream_consumers=("ML",),
        query_patterns=("ML_FEATURES",),
    )
    decision = _decide(signals)
    assert decision.presentation.rule == "P2"
    assert decision.presentation.decision == "WIDE_FEATURE_TABLE"


def test_p3_normalized_serving() -> None:
    signals = make_signals(
        downstream_consumers=("APPLICATION",),
        query_patterns=("OPERATIONAL_LOOKUP",),
    )
    decision = _decide(signals)
    assert decision.presentation.rule == "P3"


def test_p4_snowflake_schema_sets_approval() -> None:
    signals = make_signals(volume_class="L", cost_sensitivity="HIGH")
    ctx = ModellingContext(
        dimension_hierarchies=(
            DimensionHierarchyHint(
                entity="geography",
                levels=("continent", "country", "state", "city"),
                independent_change_rates=True,
            ),
        )
    )
    decision = _decide(signals, context=ctx)
    assert "P4" in decision.rule_ids
    assert decision.approval_required is True
    assert "P4" in decision.approval_reasons
    assert "cost_class" not in decision.approval_reasons


def test_p5_unknown_consumers() -> None:
    signals = make_signals(downstream_consumers=("UNKNOWN",), query_patterns=("UNKNOWN",))
    decision = _decide(signals)
    assert decision.presentation.rule == "P5"
    assert decision.presentation.decision == "STAR_SCHEMA"
    assert any(item.rule == "P5" for item in decision.open_questions)


def test_f1_transaction_facts() -> None:
    selected = (asset("BILLING", "INVOICE_LINES"),)
    profiles = (
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            ("INVOICE_LINE_ID", "AMOUNT", "_LOADED_AT"),
            unique=("INVOICE_LINE_ID",),
            row_count=4_100_000,
        ),
    )
    decision = _decide(make_signals(volume_class="M"), selected=selected, profiles=profiles)
    assert any(item.kind == "TRANSACTION_FACT" and "F1" in item.rule for item in decision.facts)


def test_f2_periodic_snapshot_for_mrr() -> None:
    selected = (asset("BILLING", "INVOICE_LINES"),)
    profiles = (
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            ("INVOICE_LINE_ID", "AMOUNT", "_LOADED_AT"),
            unique=("INVOICE_LINE_ID",),
        ),
    )
    decision = _decide(make_signals(), selected=selected, profiles=profiles)
    snapshot_facts = [
        item
        for item in decision.facts
        if item.kind == "PERIODIC_SNAPSHOT_FACT" and "F2" in item.rule
    ]
    assert snapshot_facts


def test_f3_accumulating_snapshot_recommendation() -> None:
    requirement = vantara_demo_requirement().model_copy(
        update={"goal": "Track the order to invoice to payment milestone process"}
    )
    selected = (asset("BILLING", "INVOICE_LINES"), asset("PAYMENTS", "PAYMENTS"))
    profiles = (
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            ("INVOICE_LINE_ID", "AMOUNT"),
            unique=("INVOICE_LINE_ID",),
        ),
        make_profile(
            "PAYMENTS",
            "PAYMENTS",
            ("PAYMENT_ID", "AMOUNT"),
            unique=("PAYMENT_ID",),
        ),
    )
    decision = _decide(
        make_signals(),
        selected=selected,
        profiles=profiles,
        requirement=requirement,
    )
    assert any(item.startswith("F3:") for item in decision.recommendations)


def test_f4_duplicate_grain_requires_dedup() -> None:
    selected = (asset("PAYMENTS", "PAYMENTS"),)
    profiles = (
        make_profile(
            "PAYMENTS",
            "PAYMENTS",
            ("PAYMENT_ID", "INVOICE_ID", "PAYMENT_REF", "_LOADED_AT"),
            unique=("PAYMENT_ID",),
        ),
    )
    decision = _decide(
        make_signals(),
        selected=selected,
        profiles=profiles,
        duplicates=vantara_duplicates(),
    )
    payment = next(item for item in decision.facts if item.entity == "payment")
    assert "F4" in payment.rule
    assert payment.dedup_required is True
    assert any(item.entity == "payment" for item in decision.dedup)


def test_d1_and_d7_customer_snapshot() -> None:
    selected = (asset("CRM", "ACCOUNTS"),)
    profiles = (
        make_profile(
            "CRM",
            "ACCOUNTS",
            ("ACCOUNT_ID", "UPDATED_AT"),
            unique=("ACCOUNT_ID",),
            has_updated_at=True,
        ),
    )
    decision = _decide(
        make_signals(entity_history=(), entity_history_in_source="FALSE"),
        selected=selected,
        profiles=profiles,
    )
    customer = next(item for item in decision.dimensions if item.entity == "customer")
    assert "D1" in customer.rule
    assert "D7" in customer.rule
    assert customer.strategy == "snapshot_timestamp"


def test_d2_low_change_still_scd2() -> None:
    selected = (asset("CRM", "ACCOUNTS"),)
    profiles = (make_profile("CRM", "ACCOUNTS", ("ACCOUNT_ID",), unique=("ACCOUNT_ID",)),)
    decision = _decide(
        make_signals(change_frequency="LOW", entity_history_in_source="FALSE", entity_history=()),
        selected=selected,
        profiles=profiles,
    )
    customer = next(item for item in decision.dimensions if item.entity == "customer")
    assert "D2" in customer.rule
    assert customer.history == "SCD2"


def test_d3_current_only_is_scd1() -> None:
    selected = (asset("CRM", "ACCOUNTS"),)
    profiles = (make_profile("CRM", "ACCOUNTS", ("ACCOUNT_ID",), unique=("ACCOUNT_ID",)),)
    decision = _decide(
        make_signals(history_requirements="CURRENT_ONLY"),
        selected=selected,
        profiles=profiles,
    )
    customer = next(item for item in decision.dimensions if item.entity == "customer")
    assert customer.rule == ("D3",)
    assert customer.history == "SCD1"


def test_d4_unknown_history_is_blocking() -> None:
    selected = (asset("CRM", "ACCOUNTS"),)
    profiles = (make_profile("CRM", "ACCOUNTS", ("ACCOUNT_ID",), unique=("ACCOUNT_ID",)),)
    decision = _decide(
        make_signals(history_requirements="UNKNOWN"),
        selected=selected,
        profiles=profiles,
    )
    assert any(item.rule == "D4" and item.blocking for item in decision.open_questions)


def test_d5_hybrid_scd1_attributes() -> None:
    selected = (asset("CRM", "ACCOUNTS"),)
    profiles = (
        make_profile(
            "CRM",
            "ACCOUNTS",
            ("ACCOUNT_ID", "UPDATED_AT"),
            unique=("ACCOUNT_ID",),
            has_updated_at=True,
        ),
    )
    ctx = ModellingContext(low_value_scd1_attributes=(("customer", "phone"),))
    decision = _decide(make_signals(), selected=selected, profiles=profiles, context=ctx)
    customer = next(item for item in decision.dimensions if item.entity == "customer")
    assert "D5" in customer.rule
    assert "phone" in customer.hybrid_scd1_attributes


def test_d6_source_validity_intervals() -> None:
    selected = (asset("PRODUCT", "PLANS"),)
    profiles = (
        make_profile(
            "PRODUCT",
            "PLANS",
            ("PLAN_CODE", "VALID_FROM", "VALID_TO"),
            has_valid_from=True,
            has_valid_to=True,
        ),
    )
    from aide.capabilities.io import EntityHistorySignal

    signals = make_signals(
        entity_history=(
            EntityHistorySignal(
                entity="plan",
                asset=asset("PRODUCT", "PLANS"),
                has_source_history="TRUE",
                validity_columns=("VALID_FROM", "VALID_TO"),
            ),
        )
    )
    decision = _decide(signals, selected=selected, profiles=profiles)
    plan = next(item for item in decision.dimensions if item.entity == "plan")
    assert "D6" in plan.rule
    assert plan.strategy == "source_validity_intervals"


def test_d8_date_dimension_static() -> None:
    decision = _decide(
        make_signals(),
        selected=(asset("CRM", "ACCOUNTS"),),
        profiles=vantara_profiles()[:1],
    )
    date_dim = next(item for item in decision.dimensions if item.entity == "date")
    assert date_dim.rule == ("D8",)
    assert date_dim.history == "STATIC"


def test_m1_staging_views_for_s_and_m() -> None:
    decision = _decide(make_signals(volume_class="M"))
    staging = next(item for item in decision.materialization if item.rule == "M1")
    assert staging.materialization == "view"
    large = _decide(make_signals(volume_class="L"))
    staging_l = next(item for item in large.materialization if item.rule == "M1")
    assert staging_l.materialization == "table"


def test_m2_intermediate() -> None:
    decision = _decide(make_signals())
    assert any(item.rule == "M2" for item in decision.materialization)


def test_m3_incremental_when_volume_m_watermark_and_merge() -> None:
    selected = (asset("BILLING", "INVOICE_LINES"),)
    profiles = (
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            ("INVOICE_LINE_ID", "AMOUNT", "_LOADED_AT"),
            unique=("INVOICE_LINE_ID",),
            has_loaded_at=True,
        ),
    )
    decision = _decide(
        make_signals(volume_class="M", platform_capabilities=SNOWFLAKE_CAPABILITIES),
        selected=selected,
        profiles=profiles,
    )
    fact = next(item for item in decision.facts if item.entity == "invoice_line")
    assert fact.materialization == "incremental"
    assert "M3" in fact.rule


def test_m4_small_facts_are_tables() -> None:
    selected = (asset("BILLING", "INVOICE_LINES"),)
    profiles = (
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            ("INVOICE_LINE_ID", "AMOUNT", "_LOADED_AT"),
            unique=("INVOICE_LINE_ID",),
        ),
    )
    decision = _decide(make_signals(volume_class="S"), selected=selected, profiles=profiles)
    fact = next(item for item in decision.facts if item.entity == "invoice_line")
    assert fact.materialization == "table"
    assert "M4" in fact.rule


def test_m5_no_reliable_watermark() -> None:
    selected = (asset("BILLING", "INVOICE_LINES"),)
    profiles = (
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            ("INVOICE_LINE_ID", "AMOUNT"),
            unique=("INVOICE_LINE_ID",),
            has_loaded_at=False,
        ),
    )
    decision = _decide(make_signals(volume_class="M"), selected=selected, profiles=profiles)
    fact = next(item for item in decision.facts if item.entity == "invoice_line")
    assert "M5" in fact.rule
    assert fact.materialization == "table"


def test_m6_marts_are_tables_for_daily() -> None:
    decision = _decide(make_signals())
    assert any(item.rule == "M6" for item in decision.materialization)


def test_m7_clustering_recommendation() -> None:
    decision = _decide(make_signals(volume_class="L", cost_sensitivity="HIGH"))
    assert any(item.rule == "M7" for item in decision.materialization)
    assert decision.approval_required is False
    assert "cost_class" not in decision.approval_reasons


def test_conformance_misaligned_without_crosswalk_blocks() -> None:
    selected = (asset("CRM", "ACCOUNTS"), asset("BILLING", "CUSTOMERS"))
    profiles = (
        make_profile("CRM", "ACCOUNTS", ("ACCOUNT_ID",), unique=("ACCOUNT_ID",)),
        make_profile("BILLING", "CUSTOMERS", ("CUSTOMER_ID",), unique=("CUSTOMER_ID",)),
    )
    decision = _decide(
        make_signals(identifier_alignment="MISALIGNED"),
        selected=selected,
        profiles=profiles,
    )
    assert any(item.topic == "survivorship" and item.blocking for item in decision.open_questions)


def test_conformance_misaligned_with_crosswalk_is_not_blocking() -> None:
    selected = (
        asset("CRM", "ACCOUNTS"),
        asset("CRM", "ACCOUNT_CROSSWALK"),
        asset("BILLING", "CUSTOMERS"),
    )
    profiles = (
        make_profile("CRM", "ACCOUNTS", ("ACCOUNT_ID",), unique=("ACCOUNT_ID",)),
        make_profile(
            "CRM",
            "ACCOUNT_CROSSWALK",
            ("ACCOUNT_ID", "BILLING_CUSTOMER_ID"),
        ),
        make_profile("BILLING", "CUSTOMERS", ("CUSTOMER_ID",), unique=("CUSTOMER_ID",)),
    )
    decision = _decide(
        make_signals(identifier_alignment="MISALIGNED"),
        selected=selected,
        profiles=profiles,
    )
    questions = [item for item in decision.open_questions if item.topic == "survivorship"]
    assert questions
    assert questions[0].blocking is False
