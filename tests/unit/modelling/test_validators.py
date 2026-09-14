from __future__ import annotations

from tests.unit.modelling.factories import (
    asset,
    locked_design,
    vantara_decision,
    vantara_duplicates,
    vantara_profiles,
)

from aide.capabilities.io import (
    ArchitectureDecision,
    DesignValidationReport,
    ModelColumn,
    ModelDesign,
    ModelDesignUnit,
)
from aide.domain.sql import AssetKind, AssetRef
from aide.modelling.context import ModellingContext
from aide.modelling.validators import validate_model_design


def _report(
    design: ModelDesign | None = None,
    *,
    decision: ArchitectureDecision | None = None,
    context: ModellingContext | None = None,
) -> DesignValidationReport:
    resolved = decision or vantara_decision()
    payload = design or locked_design(resolved)
    return validate_model_design(
        payload,
        resolved,
        selected=tuple(item.asset for item in vantara_profiles()),
        profiles=vantara_profiles(),
        duplicates=vantara_duplicates(),
        context=context or ModellingContext(require_demo_models=True),
    )


def _replace(design: ModelDesign, name: str, **updates: object) -> ModelDesign:
    models = tuple(
        item.model_copy(update=updates) if item.name == name else item for item in design.models
    )
    return design.model_copy(update={"models": models})


def _drop(design: ModelDesign, name: str) -> ModelDesign:
    return design.model_copy(
        update={"models": tuple(item for item in design.models if item.name != name)}
    )


def test_valid_vantara_design_is_accepted() -> None:
    report = _report()
    assert report.passed, tuple(item.code for item in report.violations)
    required = (
        "dim_customer",
        "dim_plan",
        "fct_invoice_line",
        "fct_payment",
        "mart_customer_revenue_daily",
    )
    for name in required:
        assert name in report.required_models_present


def test_unknown_source_column_rejected() -> None:
    decision = vantara_decision()
    design = locked_design(decision)
    accounts = next(item for item in design.models if item.name == "stg_crm__accounts")
    design = _replace(
        design,
        "stg_crm__accounts",
        columns=(
            *accounts.columns,
            ModelColumn(
                name="ghost",
                expression="NOT_A_COLUMN",
                source_asset=asset("CRM", "ACCOUNTS"),
                source_column="NOT_A_COLUMN",
            ),
        ),
    )
    report = _report(design, decision=decision)
    assert not report.passed
    assert any(item.code == "UNKNOWN_SOURCE_COLUMN" for item in report.violations)


def test_wrong_grain_rejected() -> None:
    decision = vantara_decision()
    design = _replace(
        locked_design(decision),
        "fct_invoice_line",
        grain=("not_a_grain",),
        unique_key=("not_a_grain",),
    )
    report = _report(design, decision=decision)
    assert any(item.code == "FACT_GRAIN_EVIDENCE_INVALID" for item in report.violations)


def test_v2_payment_natural_uniqueness_rejected() -> None:
    decision = vantara_decision()
    design = _replace(
        locked_design(decision),
        "fct_payment",
        dedup_rule=None,
        dependencies=("stg_payments__payments",),
    )
    report = _report(design, decision=decision)
    assert any(item.code == "PAYMENT_NATURAL_UNIQUENESS_REJECTED" for item in report.violations)


def test_missing_customer_dedup_rejected() -> None:
    decision = vantara_decision()
    design = _drop(locked_design(decision), "int_customer_deduplicated")
    report = _report(design, decision=decision)
    assert any(item.code == "CUSTOMER_DEDUP_MISSING" for item in report.violations)


def test_invalid_scd2_strategy_rejected() -> None:
    decision = vantara_decision()
    design = _replace(
        locked_design(decision),
        "dim_plan",
        history_strategy="snapshot_timestamp",
    )
    report = _report(design, decision=decision)
    assert any(item.code == "SCD2_STRATEGY_INVALID" for item in report.violations)


def test_data_vault_generation_rejected() -> None:
    decision = vantara_decision()
    design = locked_design(decision)
    hub = ModelDesignUnit(
        name="int_hub_customer",
        model_kind="HUB",
        layer="intermediate",
        grain=("customer_id",),
        materialization="table",
    )
    design = design.model_copy(update={"models": (*design.models, hub)})
    report = _report(design, decision=decision)
    assert any(item.code == "DATA_VAULT_GENERATION_REJECTED" for item in report.violations)


def test_dependency_cycle_rejected() -> None:
    decision = vantara_decision()
    design = locked_design(decision)
    design = _replace(design, "dim_customer", dependencies=("fct_invoice_line",))
    design = _replace(design, "fct_invoice_line", dependencies=("dim_customer",))
    report = _report(design, decision=decision)
    assert any(item.code == "DEPENDENCY_CYCLE" for item in report.violations)


def test_missing_required_model_rejected() -> None:
    decision = vantara_decision()
    design = _drop(locked_design(decision), "dim_customer")
    report = _report(design, decision=decision)
    assert any(item.code == "REQUIRED_MODEL_MISSING" for item in report.violations)


def test_architecture_override_digest_rejected() -> None:
    decision = vantara_decision()
    design = locked_design(decision).model_copy(update={"architecture_decision_digest": "a" * 64})
    report = _report(design, decision=decision)
    assert any(item.code == "ARCHITECTURE_OVERRIDE" for item in report.violations)


def test_unsupported_kind_rejected() -> None:
    decision = vantara_decision()
    design = locked_design(decision)
    extra = ModelDesignUnit(
        name="int_weird",
        model_kind="SATELLITE",
        layer="intermediate",
        grain=("id",),
        materialization="table",
    )
    extra_models = (*design.models, extra)
    report = _report(design.model_copy(update={"models": extra_models}), decision=decision)
    assert any(
        item.code in {"UNSUPPORTED_MODEL_KIND", "DATA_VAULT_GENERATION_REJECTED"}
        for item in report.violations
    )


def test_pii_sample_rejected() -> None:
    decision = vantara_decision()
    design = locked_design(decision)
    design = _replace(
        design,
        "stg_crm__contacts",
        assumptions=("contact email is jane@example.com",),
    )
    report = _report(design, decision=decision)
    assert any(item.code == "PII_SAMPLE_EXPOSED" for item in report.violations)


def test_unknown_source_asset_rejected() -> None:
    decision = vantara_decision()
    ghost = AssetRef(
        connector_id="snowflake_ro",
        address=("VANTARA_RAW", "OTHER", "GHOST"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    design = _replace(locked_design(decision), "stg_crm__accounts", source_assets=(ghost,))
    report = _report(design, decision=decision)
    assert any(item.code == "UNKNOWN_SOURCE_ASSET" for item in report.violations)
