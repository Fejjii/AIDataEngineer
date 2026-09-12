"""Shared modelling test factories."""

from __future__ import annotations

from aide.capabilities.io import (
    ArchitectureDecision,
    AssetProfileEvidence,
    CandidateKey,
    DuplicateEvidenceLite,
    ModelDesign,
    ModellingSignals,
    RelationshipCandidate,
    RequirementSpec,
)
from aide.domain.sql import AssetKind, AssetRef
from aide.modelling.context import ModellingContext
from aide.modelling.demo_design import vantara_model_design
from aide.modelling.engine import ModellingDecisionEngine
from aide.modelling.platform import SNOWFLAKE_CAPABILITIES
from aide.modelling.vantara import vantara_demo_requirement, vantara_modelling_context
from aide.profiling.fixtures import demo_selected_assets


def asset(schema: str, table: str) -> AssetRef:
    return AssetRef(
        connector_id="snowflake_ro",
        address=("VANTARA_RAW", schema, table),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )


def make_signals(**overrides: object) -> ModellingSignals:
    payload: dict[str, object] = {
        "deliverable_type": "ANALYTICAL_DATA_PRODUCT",
        "history_requirements": "FULL_HISTORY",
        "auditability": "LOW",
        "source_count": 10,
        "source_system_count": 4,
        "source_structure": "NORMALIZED_3NF",
        "volume_class": "M",
        "volume_row_count": 4_100_000,
        "velocity": "BATCH_DAILY",
        "change_frequency": "MEDIUM",
        "entity_history_in_source": "TRUE",
        "query_patterns": ("AGGREGATE_BI",),
        "downstream_consumers": ("BI",),
        "latency_requirement": "DAILY",
        "platform_capabilities": SNOWFLAKE_CAPABILITIES,
        "cost_sensitivity": "UNKNOWN",
        "key_quality": "DUPLICATES_PRESENT",
        "identifier_alignment": "PARTIAL",
        "identifier_alignment_ratio": 0.962,
    }
    payload.update(overrides)
    return ModellingSignals.model_validate(payload)


def make_profile(
    schema: str,
    table: str,
    columns: tuple[str, ...],
    *,
    row_count: int = 100,
    unique: tuple[str, ...] = (),
    composite: tuple[tuple[tuple[str, ...], float, bool], ...] = (),
    has_valid_from: bool = False,
    has_valid_to: bool = False,
    has_updated_at: bool = False,
    has_loaded_at: bool = True,
    loaded_at_null_ratio: float = 0.0,
) -> AssetProfileEvidence:
    keys = tuple(CandidateKey(columns=(name,), uniqueness_ratio=1.0) for name in unique)
    composite_full = composite
    if unique and not composite:
        composite_full = tuple(((name,), 1.0, True) for name in unique)
    return AssetProfileEvidence(
        asset=asset(schema, table),
        row_count=row_count,
        columns=columns,
        column_types=tuple((name, "VARCHAR") for name in columns),
        candidate_keys=keys,
        composite_key_uniqueness=composite_full,
        has_valid_from=has_valid_from,
        has_valid_to=has_valid_to,
        has_updated_at=has_updated_at,
        has_loaded_at=has_loaded_at,
        loaded_at_null_ratio=loaded_at_null_ratio,
        updated_at_null_ratio=0.0 if has_updated_at else None,
    )


def vantara_profiles() -> tuple[AssetProfileEvidence, ...]:
    loaded = ("_LOADED_AT", "_EXTRACT_DATE", "_SOURCE_FILE")
    return (
        make_profile(
            "CRM",
            "ACCOUNTS",
            (
                "ACCOUNT_ID",
                "ACCOUNT_NAME",
                "WEBSITE_DOMAIN",
                "INDUSTRY",
                "COUNTRY",
                "OWNER_ID",
                "CREATED_AT",
                "UPDATED_AT",
                "IS_DELETED",
                *loaded,
            ),
            unique=("ACCOUNT_ID",),
            has_updated_at=True,
        ),
        make_profile(
            "CRM",
            "CONTACTS",
            (
                "CONTACT_ID",
                "ACCOUNT_ID",
                "FIRST_NAME",
                "LAST_NAME",
                "EMAIL",
                "PHONE",
                "CREATED_AT",
                "UPDATED_AT",
                *loaded,
            ),
            unique=("CONTACT_ID",),
        ),
        make_profile(
            "CRM",
            "ACCOUNT_CROSSWALK",
            ("ACCOUNT_ID", "BILLING_CUSTOMER_ID", "CREATED_AT", *loaded),
            composite=((("ACCOUNT_ID", "BILLING_CUSTOMER_ID"), 1.0, True),),
        ),
        make_profile(
            "BILLING",
            "CUSTOMERS",
            (
                "CUSTOMER_ID",
                "CUSTOMER_NAME",
                "CRM_ACCOUNT_ID",
                "BILLING_COUNTRY",
                "CREATED_AT",
                "UPDATED_AT",
                *loaded,
            ),
            unique=("CUSTOMER_ID",),
            has_updated_at=True,
        ),
        make_profile(
            "BILLING",
            "SUBSCRIPTIONS",
            (
                "SUBSCRIPTION_ID",
                "CUSTOMER_ID",
                "PLAN_CODE",
                "STATUS",
                "START_DATE",
                "END_DATE",
                "UPDATED_AT",
                *loaded,
            ),
            unique=("SUBSCRIPTION_ID",),
            has_updated_at=True,
        ),
        make_profile(
            "BILLING",
            "INVOICES",
            (
                "INVOICE_ID",
                "CUSTOMER_ID",
                "CURRENCY",
                "ISSUE_DATE",
                "DUE_DATE",
                "TOTAL_AMOUNT",
                "STATUS",
                *loaded,
            ),
            unique=("INVOICE_ID",),
        ),
        make_profile(
            "BILLING",
            "INVOICE_LINES",
            (
                "INVOICE_LINE_ID",
                "INVOICE_ID",
                "PLAN_CODE",
                "QUANTITY",
                "UNIT_PRICE",
                "AMOUNT",
                "SERVICE_PERIOD_START",
                "SERVICE_PERIOD_END",
                *loaded,
            ),
            unique=("INVOICE_LINE_ID",),
            row_count=4_100_000,
        ),
        make_profile(
            "PAYMENTS",
            "PAYMENTS",
            (
                "PAYMENT_ID",
                "INVOICE_ID",
                "PAYMENT_REF",
                "AMOUNT",
                "PAID_AT",
                *loaded,
            ),
            unique=("PAYMENT_ID",),
            composite=(
                (("PAYMENT_ID",), 1.0, True),
                (("INVOICE_ID", "PAYMENT_REF"), 0.985, False),
            ),
        ),
        make_profile(
            "PAYMENTS",
            "REFUNDS",
            ("REFUND_ID", "PAYMENT_ID", "AMOUNT", "REFUNDED_AT", *loaded),
            unique=("REFUND_ID",),
        ),
        make_profile(
            "PRODUCT",
            "PLANS",
            (
                "PLAN_CODE",
                "PLAN_NAME",
                "VALID_FROM",
                "VALID_TO",
                "MONTHLY_PRICE",
                *loaded,
            ),
            composite=((("PLAN_CODE", "VALID_FROM"), 1.0, True),),
            has_valid_from=True,
            has_valid_to=True,
        ),
    )


def vantara_duplicates() -> tuple[DuplicateEvidenceLite, ...]:
    return (
        DuplicateEvidenceLite(
            asset=asset("CRM", "ACCOUNTS"),
            columns=("WEBSITE_DOMAIN",),
            uniqueness_ratio=0.93,
            duplicate_groups_estimate=7,
            extra_row_estimate=10,
            reason="duplicate CRM accounts",
        ),
        DuplicateEvidenceLite(
            asset=asset("PAYMENTS", "PAYMENTS"),
            columns=("INVOICE_ID", "PAYMENT_REF"),
            uniqueness_ratio=0.985,
            duplicate_groups_estimate=5,
            extra_row_estimate=8,
            reason="duplicate payment rows",
        ),
    )


def vantara_relationships() -> tuple[RelationshipCandidate, ...]:
    return (
        RelationshipCandidate(
            from_asset=asset("BILLING", "CUSTOMERS"),
            from_columns=("CUSTOMER_ID",),
            to_asset=asset("CRM", "ACCOUNT_CROSSWALK"),
            to_columns=("BILLING_CUSTOMER_ID",),
            inclusion_ratio=0.962,
            cardinality="1:N",
            confidence=0.97,
        ),
    )


def vantara_decision(
    requirement: RequirementSpec | None = None,
    *,
    context: ModellingContext | None = None,
    signals: ModellingSignals | None = None,
) -> ArchitectureDecision:
    engine = ModellingDecisionEngine()
    return engine.decide(
        requirement or vantara_demo_requirement(),
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        relationships=vantara_relationships(),
        duplicates=vantara_duplicates(),
        context=context or vantara_modelling_context(),
        signals=signals,
    )


def locked_design(decision: ArchitectureDecision) -> ModelDesign:
    from aide.domain.identity import compute_resolved_input_digest

    digest = compute_resolved_input_digest(decision)
    return vantara_model_design(architecture_decision_digest=digest)
