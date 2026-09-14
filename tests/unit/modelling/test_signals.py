from __future__ import annotations

from tests.unit.modelling.factories import (
    asset,
    make_profile,
    vantara_duplicates,
    vantara_profiles,
    vantara_relationships,
)

from aide.capabilities.io import PlatformCapabilities, RelationshipCandidate, RequirementSpec
from aide.modelling.context import ModellingContext, OrgModellingConfig
from aide.modelling.signals import (
    classify_identifier_alignment,
    classify_volume,
    extract_modelling_signals,
)
from aide.modelling.vantara import vantara_demo_requirement, vantara_modelling_context
from aide.profiling.fixtures import demo_selected_assets


def test_volume_thresholds() -> None:
    assert classify_volume(999_999) == "S"
    assert classify_volume(1_000_000) == "M"
    assert classify_volume(49_999_999) == "M"
    assert classify_volume(50_000_000) == "L"
    assert classify_volume(1_000_000_000) == "L"
    assert classify_volume(1_000_000_001) == "XL"


def test_identifier_alignment_thresholds() -> None:
    assert classify_identifier_alignment(0.99) == "ALIGNED"
    assert classify_identifier_alignment(1.0) == "ALIGNED"
    assert classify_identifier_alignment(0.989) == "PARTIAL"
    assert classify_identifier_alignment(0.9) == "PARTIAL"
    assert classify_identifier_alignment(0.899) == "MISALIGNED"


def test_unknown_signals_are_not_guessed() -> None:
    requirement = RequirementSpec(
        goal="Do something",
        deliverable_type="INVESTIGATION",
        history_requirements="UNKNOWN",
    )
    signals = extract_modelling_signals(requirement, selected=())
    assert signals.auditability == "UNKNOWN"
    assert signals.source_count is None
    assert signals.volume_class == "UNKNOWN"
    assert signals.velocity == "UNKNOWN"
    assert signals.latency_requirement == "UNKNOWN"
    assert signals.change_frequency == "UNKNOWN"
    assert signals.identifier_alignment == "UNKNOWN"
    assert signals.downstream_consumers == ("UNKNOWN",)
    assert signals.query_patterns == ("UNKNOWN",)
    assert "auditability" in signals.unknown_reasons
    assert "volume_class" in signals.unknown_reasons


def test_deliverable_and_history_from_requirement() -> None:
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        relationships=vantara_relationships(),
        duplicates=vantara_duplicates(),
        context=vantara_modelling_context(),
    )
    assert signals.deliverable_type == "ANALYTICAL_DATA_PRODUCT"
    assert signals.history_requirements == "FULL_HISTORY"
    assert signals.auditability == "LOW"
    assert signals.source_count == 10
    assert signals.source_system_count == 4
    assert signals.source_structure == "NORMALIZED_3NF"
    assert signals.volume_class == "M"
    assert signals.volume_row_count == 4_100_000
    assert signals.velocity == "BATCH_DAILY"
    assert signals.latency_requirement == "DAILY"
    assert signals.downstream_consumers == ("BI",)
    assert "AGGREGATE_BI" in signals.query_patterns
    assert signals.platform_capabilities.supports_merge == "TRUE"
    assert signals.key_quality == "DUPLICATES_PRESENT"
    assert signals.identifier_alignment == "PARTIAL"
    assert signals.identifier_alignment_ratio == 0.962
    assert signals.entity_history_in_source == "TRUE"
    plan = next(item for item in signals.entity_history if item.entity == "plan")
    customer = next(item for item in signals.entity_history if item.entity == "customer")
    assert plan.has_source_history == "TRUE"
    assert customer.has_source_history == "FALSE"


def test_auditability_high_from_constraints() -> None:
    requirement = vantara_demo_requirement().model_copy(
        update={"constraints": ("SOX audit required",)}
    )
    signals = extract_modelling_signals(
        requirement, selected=(), context=ModellingContext(org=OrgModellingConfig())
    )
    assert signals.auditability == "HIGH"


def test_auditability_low_from_constraints() -> None:
    requirement = vantara_demo_requirement().model_copy(
        update={"constraints": ("internal only, non-regulated",)}
    )
    signals = extract_modelling_signals(
        requirement, selected=(), context=ModellingContext(org=OrgModellingConfig())
    )
    assert signals.auditability == "LOW"


def test_freshness_hourly_and_minutes() -> None:
    hourly = vantara_demo_requirement().model_copy(update={"freshness_requirement": "hourly"})
    minutes = vantara_demo_requirement().model_copy(
        update={"freshness_requirement": "near real-time minutes"}
    )
    assert extract_modelling_signals(hourly, selected=()).velocity == "INTRA_DAY"
    assert extract_modelling_signals(hourly, selected=()).latency_requirement == "HOURLY"
    assert extract_modelling_signals(minutes, selected=()).velocity == "NEAR_REAL_TIME"
    assert extract_modelling_signals(minutes, selected=()).latency_requirement == "MINUTES"


def test_consumers_ml_and_application() -> None:
    ml = vantara_demo_requirement().model_copy(update={"consumers": ("ML",)})
    app = vantara_demo_requirement().model_copy(update={"consumers": ("application",)})
    assert extract_modelling_signals(ml, selected=()).downstream_consumers == ("ML",)
    assert extract_modelling_signals(app, selected=()).downstream_consumers == ("APPLICATION",)


def test_platform_unknown_without_vendor() -> None:
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(),
        platform=PlatformCapabilities(),
    )
    assert signals.platform_capabilities.supports_merge == "UNKNOWN"


def test_cost_sensitivity_from_constraints() -> None:
    requirement = vantara_demo_requirement().model_copy(
        update={"constraints": ("minimize cost, warehouse cost",)}
    )
    signals = extract_modelling_signals(requirement, selected=())
    assert signals.cost_sensitivity == "HIGH"


def test_key_quality_clean_and_no_natural_key() -> None:
    clean = (make_profile("SALES", "ORDERS", ("ORDER_ID",), unique=("ORDER_ID",)),)
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("SALES", "ORDERS"),),
        profiles=clean,
    )
    assert signals.key_quality == "CLEAN"
    empty = (make_profile("SALES", "JUNK", ("NOTE",)),)
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("SALES", "JUNK"),),
        profiles=empty,
    )
    assert signals.key_quality == "NO_NATURAL_KEY"


def test_change_frequency_from_updated_at_and_validity() -> None:
    updated = (
        make_profile(
            "CRM",
            "ACCOUNTS",
            ("ACCOUNT_ID", "UPDATED_AT"),
            unique=("ACCOUNT_ID",),
            has_updated_at=True,
        ),
    )
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("CRM", "ACCOUNTS"),),
        profiles=updated,
    )
    assert signals.change_frequency == "MEDIUM"
    plans = (
        make_profile(
            "PRODUCT",
            "PLANS",
            ("PLAN_CODE", "VALID_FROM", "VALID_TO"),
            has_valid_from=True,
            has_valid_to=True,
        ),
    )
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("PRODUCT", "PLANS"),),
        profiles=plans,
    )
    assert signals.change_frequency == "HIGH"


def test_identifier_alignment_prefers_crosswalk() -> None:
    weak = RelationshipCandidate(
        from_asset=asset("BILLING", "CUSTOMERS"),
        from_columns=("CRM_ACCOUNT_ID",),
        to_asset=asset("CRM", "ACCOUNTS"),
        to_columns=("ACCOUNT_ID",),
        inclusion_ratio=0.7,
        cardinality="1:1",
        confidence=0.7,
    )
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        relationships=(*vantara_relationships(), weak),
        duplicates=vantara_duplicates(),
        context=vantara_modelling_context(),
    )
    assert signals.identifier_alignment == "PARTIAL"
    assert signals.identifier_alignment_ratio == 0.962


def test_identifier_alignment_ignores_reverse_crosswalk_coverage() -> None:
    reverse = RelationshipCandidate(
        from_asset=asset("CRM", "ACCOUNT_CROSSWALK"),
        from_columns=("ACCOUNT_ID",),
        to_asset=asset("BILLING", "CUSTOMERS"),
        to_columns=("CRM_ACCOUNT_ID",),
        inclusion_ratio=0.854839,
        cardinality="1:N",
        confidence=0.85,
    )
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        relationships=(*vantara_relationships(), reverse),
        duplicates=vantara_duplicates(),
        context=vantara_modelling_context(),
    )
    assert signals.identifier_alignment == "PARTIAL"
    assert signals.identifier_alignment_ratio == 0.962


def test_source_structure_event_log_and_unknown() -> None:
    events = (make_profile("USAGE", "EVENTS", ("EVENT_ID", "TS"), unique=("EVENT_ID",)),)
    signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("USAGE", "EVENTS"),),
        profiles=events,
    )
    assert signals.source_structure == "EVENT_LOG"
    empty = extract_modelling_signals(vantara_demo_requirement(), selected=())
    assert empty.source_structure == "UNKNOWN"


def test_source_structure_denormalized_and_mixed() -> None:
    wide = (
        make_profile(
            "EXTRACT",
            "CUSTOMER_FLAT",
            tuple(f"COL_{index}" for index in range(25)),
        ),
    )
    denormalized = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("EXTRACT", "CUSTOMER_FLAT"),),
        profiles=wide,
    )
    assert denormalized.source_structure == "DENORMALIZED_EXTRACT"
    mixed = (
        make_profile("USAGE", "EVENTS", ("EVENT_ID", "TS"), unique=("EVENT_ID",)),
        make_profile("CRM", "ACCOUNTS", ("ACCOUNT_ID",), unique=("ACCOUNT_ID",)),
    )
    mixed_signals = extract_modelling_signals(
        vantara_demo_requirement(),
        selected=(asset("USAGE", "EVENTS"), asset("CRM", "ACCOUNTS")),
        profiles=mixed,
    )
    assert mixed_signals.source_structure == "MIXED"


def test_query_pattern_drill_down() -> None:
    requirement = vantara_demo_requirement().model_copy(
        update={"goal": vantara_demo_requirement().goal + " Support drill-down by customer."}
    )
    signals = extract_modelling_signals(requirement, selected=())
    assert "DRILL_DOWN" in signals.query_patterns
    assert "AGGREGATE_BI" in signals.query_patterns
