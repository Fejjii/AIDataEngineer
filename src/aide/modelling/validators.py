"""Deterministic ModelDesign validators. Violations are returned, never repaired."""

from __future__ import annotations

import re

from aide.capabilities.io import (
    ArchitectureDecision,
    AssetProfileEvidence,
    DesignValidationReport,
    DesignViolation,
    DuplicateEvidenceLite,
    ModelDesign,
    ModelDesignUnit,
    RelationshipCandidate,
    canonical_model_layers,
    physical_layer_names,
)
from aide.domain.identity import compute_resolved_input_digest
from aide.domain.sql import AssetRef
from aide.modelling.constants import (
    DIMENSION_NAME,
    FACT_NAME,
    GRAIN_UNIQUENESS,
    INTERMEDIATE_NAME,
    MART_NAME,
    REQUIRED_DEMO_MODELS,
    SNAPSHOT_NAME,
    STAGING_NAME,
    VAULT_KINDS,
)
from aide.modelling.context import ModellingContext

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"^\+?\d[\d\-\s()]{6,}$")
_NAME_BY_KIND = {
    "STAGING": STAGING_NAME,
    "INTERMEDIATE": INTERMEDIATE_NAME,
    "DIMENSION": DIMENSION_NAME,
    "FACT": FACT_NAME,
    "MART": MART_NAME,
    "SNAPSHOT": SNAPSHOT_NAME,
}


def validate_model_design(
    design: ModelDesign,
    decision: ArchitectureDecision,
    *,
    selected: tuple[AssetRef, ...],
    profiles: tuple[AssetProfileEvidence, ...] = (),
    relationships: tuple[RelationshipCandidate, ...] = (),
    duplicates: tuple[DuplicateEvidenceLite, ...] = (),
    context: ModellingContext | None = None,
) -> DesignValidationReport:
    del relationships
    ctx = context or ModellingContext()
    violations: list[DesignViolation] = []
    by_name = {item.name: item for item in design.models}
    selected_addresses = {asset.address for asset in selected}
    columns_by_asset = {
        item.asset.address: {column.upper() for column in item.columns} for item in profiles
    }
    uniqueness = _uniqueness_index(profiles)
    violations.extend(_architecture_invariants(design, decision))
    violations.extend(_source_references(design, selected_addresses, columns_by_asset))
    violations.extend(_naming(design))
    violations.extend(_dependencies(design))
    violations.extend(_facts(design, decision, uniqueness, duplicates))
    violations.extend(_dedup(design, decision, duplicates))
    violations.extend(_scd(design, decision))
    violations.extend(_kinds(design))
    violations.extend(_pii(design))
    required = _required_models(decision, ctx)
    present = tuple(name for name in required if name in by_name)
    for name in required:
        if name not in by_name:
            violations.append(
                DesignViolation(
                    code="REQUIRED_MODEL_MISSING",
                    message=f"required model {name} is missing",
                    model_name=name,
                )
            )
    return DesignValidationReport(
        passed=not violations,
        violations=tuple(violations),
        required_models_present=present,
        checked_rule_refs=decision.rule_ids,
    )


def _required_models(decision: ArchitectureDecision, ctx: ModellingContext) -> tuple[str, ...]:
    if ctx.require_demo_models:
        return REQUIRED_DEMO_MODELS
    if decision.layering.rule in {"L3", "L4"}:
        return ()
    names: list[str] = []
    if any(item.entity == "customer" for item in decision.dimensions):
        names.extend(["dim_customer", "int_customer_deduplicated", "int_customer_conformed"])
    if any(item.entity == "plan" for item in decision.dimensions):
        names.append("dim_plan")
    if any(item.entity == "date" for item in decision.dimensions):
        names.append("dim_date")
    if any(item.entity == "invoice_line" for item in decision.facts):
        names.append("fct_invoice_line")
    if any(item.entity == "payment" for item in decision.facts):
        names.extend(["fct_payment", "int_payments_deduplicated"])
    if any(item.entity == "customer_revenue_daily" for item in decision.facts):
        names.append("mart_customer_revenue_daily")
    return tuple(names)


def _architecture_invariants(
    design: ModelDesign, decision: ArchitectureDecision
) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    expected_digest = compute_resolved_input_digest(decision)
    if design.architecture_decision_digest != expected_digest:
        violations.append(
            DesignViolation(
                code="ARCHITECTURE_OVERRIDE",
                message=(
                    "ModelDesign architecture_decision_digest does not match ArchitectureDecision"
                ),
            )
        )
    expected_layers = canonical_model_layers(decision.layering.decision)
    if tuple(design.layers) != expected_layers:
        violations.append(
            DesignViolation(
                code="PRESENTATION_CLASS_CONTRADICTED",
                message="ModelDesign layers contradict ArchitectureDecision",
                details=tuple(design.layers),
            )
        )
    expected_physical = physical_layer_names(decision.naming, decision.layering.decision)
    actual_physical = design.physical_layer_names or tuple((name, name) for name in design.layers)
    if actual_physical != expected_physical:
        violations.append(
            DesignViolation(
                code="PHYSICAL_LAYER_MAPPING_INVALID",
                message="physical layer names contradict ArchitectureDecision naming",
                details=tuple(f"{src}->{dst}" for src, dst in actual_physical),
            )
        )
    if any(item.layer not in {"staging", "intermediate", "marts"} for item in design.models):
        violations.append(
            DesignViolation(
                code="PHYSICAL_LAYER_MAPPING_INVALID",
                message="ModelDesignUnit.layer must stay canonical staging/intermediate/marts",
            )
        )
    if decision.presentation.decision == "STAR_SCHEMA" and any(
        item.model_kind in VAULT_KINDS for item in design.models
    ):
        violations.append(
            DesignViolation(
                code="PRESENTATION_CLASS_CONTRADICTED",
                message="presentation class is STAR_SCHEMA but vault-like models are present",
            )
        )
    if decision.integration_layer.decision == "NO_VAULT" and any(
        "vault" in item.name or item.model_kind in VAULT_KINDS for item in design.models
    ):
        violations.append(
            DesignViolation(
                code="DATA_VAULT_GENERATION_REJECTED",
                message="Data Vault models cannot be generated in V1",
            )
        )
    if decision.layering.decision == "STAGING_INTERMEDIATE_MARTS" and not any(
        item.layer == "staging" for item in design.models
    ):
        violations.append(
            DesignViolation(
                code="PRESENTATION_CLASS_CONTRADICTED",
                message="STAGING_INTERMEDIATE_MARTS requires staging models",
            )
        )
    return violations


def _source_references(
    design: ModelDesign,
    selected_addresses: set[tuple[str, ...]],
    columns_by_asset: dict[tuple[str, ...], set[str]],
) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    for model in design.models:
        for asset in model.source_assets:
            if selected_addresses and asset.address not in selected_addresses:
                violations.append(
                    DesignViolation(
                        code="UNKNOWN_SOURCE_ASSET",
                        message=f"source asset {asset.address} is not in the selection",
                        model_name=model.name,
                    )
                )
        for column in model.columns:
            if column.source_asset is None or column.source_column is None:
                continue
            if selected_addresses and column.source_asset.address not in selected_addresses:
                violations.append(
                    DesignViolation(
                        code="UNKNOWN_SOURCE_ASSET",
                        message=f"column {column.name} references unknown asset",
                        model_name=model.name,
                    )
                )
                continue
            known = columns_by_asset.get(column.source_asset.address)
            if known is not None and column.source_column.upper() not in known:
                violations.append(
                    DesignViolation(
                        code="UNKNOWN_SOURCE_COLUMN",
                        message=(
                            f"source column {column.source_column} does not exist on "
                            f"{column.source_asset.address}"
                        ),
                        model_name=model.name,
                        details=(column.source_column,),
                    )
                )
    return violations


def _naming(design: ModelDesign) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    for model in design.models:
        pattern = _NAME_BY_KIND.get(model.model_kind)
        if pattern is None:
            continue
        if not re.match(pattern, model.name):
            violations.append(
                DesignViolation(
                    code="INVALID_MODEL_NAME",
                    message=f"{model.name} does not match {model.model_kind} naming convention",
                    model_name=model.name,
                )
            )
    return violations


def _dependencies(design: ModelDesign) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    names = {item.name for item in design.models}
    graph: dict[str, tuple[str, ...]] = {}
    for model in design.models:
        missing = tuple(dep for dep in model.dependencies if dep not in names)
        for dep in missing:
            violations.append(
                DesignViolation(
                    code="MISSING_DEPENDENCY",
                    message=f"{model.name} depends on missing model {dep}",
                    model_name=model.name,
                    details=(dep,),
                )
            )
        graph[model.name] = model.dependencies
    cycle = _first_cycle(graph)
    if cycle is not None:
        violations.append(
            DesignViolation(
                code="DEPENDENCY_CYCLE",
                message="model dependency graph contains a cycle",
                details=cycle,
            )
        )
    return violations


def _first_cycle(graph: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    visiting: set[str] = set()
    seen: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visiting:
            start = stack.index(node)
            return tuple(stack[start:] + [node])
        if node in seen:
            return None
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, ()):
            found = visit(nxt)
            if found is not None:
                return found
        stack.pop()
        visiting.remove(node)
        seen.add(node)
        return None

    for name in graph:
        found = visit(name)
        if found is not None:
            return found
    return None


def _facts(
    design: ModelDesign,
    decision: ArchitectureDecision,
    uniqueness: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, bool]],
    duplicates: tuple[DuplicateEvidenceLite, ...],
) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    for model in design.models:
        if model.model_kind != "FACT":
            continue
        if not model.grain:
            violations.append(
                DesignViolation(
                    code="FACT_GRAIN_UNDEFINED",
                    message=f"fact {model.name} has no grain",
                    model_name=model.name,
                )
            )
            continue
        if model.dedup_rule is None and _grain_needs_dedup(model, uniqueness, duplicates):
            violations.append(
                DesignViolation(
                    code="DUPLICATE_GRAIN_WITHOUT_DEDUP",
                    message=f"fact {model.name} claims uniqueness without a dedup rule",
                    model_name=model.name,
                )
            )
        if model.dedup_rule is None:
            evidence = _grain_evidence(model, uniqueness)
            if evidence is None:
                violations.append(
                    DesignViolation(
                        code="FACT_GRAIN_EVIDENCE_INVALID",
                        message=f"fact {model.name} grain is not a profiled candidate key",
                        model_name=model.name,
                    )
                )
            else:
                ratio, is_candidate = evidence
                if ratio < GRAIN_UNIQUENESS or not is_candidate:
                    violations.append(
                        DesignViolation(
                            code="FACT_GRAIN_EVIDENCE_INVALID",
                            message=(
                                f"fact {model.name} grain uniqueness {ratio} is below 0.999 "
                                "and no dedup rule is declared"
                            ),
                            model_name=model.name,
                        )
                    )
        if model.name == "fct_payment" or any(
            asset.address[-1] == "PAYMENTS" for asset in model.source_assets
        ):
            if model.dedup_rule is None:
                violations.append(
                    DesignViolation(
                        code="PAYMENT_NATURAL_UNIQUENESS_REJECTED",
                        message="v2 payment duplicates cannot be treated as naturally unique",
                        model_name=model.name,
                    )
                )
            if "int_payments_deduplicated" not in model.dependencies and any(
                item.entity == "payment" and item.dedup_required for item in decision.facts
            ):
                violations.append(
                    DesignViolation(
                        code="PAYMENT_NATURAL_UNIQUENESS_REJECTED",
                        message="fct_payment must depend on int_payments_deduplicated",
                        model_name=model.name,
                    )
                )
    return violations


def _uniqueness_index(
    profiles: tuple[AssetProfileEvidence, ...],
) -> dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, bool]]:
    index: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, bool]] = {}
    for profile in profiles:
        for columns, ratio, is_candidate in profile.composite_key_uniqueness:
            key = (profile.asset.address, tuple(column.upper() for column in columns))
            index[key] = (ratio, is_candidate)
        for candidate in profile.candidate_keys:
            addr_key = (
                profile.asset.address,
                tuple(column.upper() for column in candidate.columns),
            )
            index[addr_key] = (candidate.uniqueness_ratio, True)
    return index


def _grain_evidence(
    model: ModelDesignUnit,
    uniqueness: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, bool]],
) -> tuple[float, bool] | None:
    grain = tuple(item.upper() for item in model.grain)
    for asset in model.source_assets:
        found = uniqueness.get((asset.address, grain))
        if found is not None:
            return found
    return None


def _grain_needs_dedup(
    model: ModelDesignUnit,
    uniqueness: dict[tuple[tuple[str, ...], tuple[str, ...]], tuple[float, bool]],
    duplicates: tuple[DuplicateEvidenceLite, ...],
) -> bool:
    for item in duplicates:
        if any(asset.address == item.asset.address for asset in model.source_assets) and (
            item.uniqueness_ratio < 1.0 or item.extra_row_estimate > 0
        ):
            return True
    evidence = _grain_evidence(model, uniqueness)
    if evidence is None:
        return False
    ratio, is_candidate = evidence
    return ratio < GRAIN_UNIQUENESS or not is_candidate


def _dedup(
    design: ModelDesign,
    decision: ArchitectureDecision,
    duplicates: tuple[DuplicateEvidenceLite, ...],
) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    names = {item.name for item in design.models}
    crm_dupes = any(
        item.asset.address[-1] == "ACCOUNTS"
        and (item.uniqueness_ratio < 1.0 or item.extra_row_estimate > 0)
        for item in duplicates
    ) or any(item.entity == "customer" for item in decision.dedup)
    if crm_dupes and "int_customer_deduplicated" not in names:
        violations.append(
            DesignViolation(
                code="CUSTOMER_DEDUP_MISSING",
                message="CRM domain duplicates require int_customer_deduplicated",
                model_name="int_customer_deduplicated",
            )
        )
    return violations


def _scd(design: ModelDesign, decision: ArchitectureDecision) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    by_name = {item.name: item for item in design.models}
    for dim in decision.dimensions:
        model_name = f"dim_{dim.entity}"
        model = by_name.get(model_name)
        if dim.history == "SCD2" and model is None:
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message=f"required SCD2 dimension {model_name} is missing",
                    model_name=model_name,
                )
            )
            continue
        if model is None:
            continue
        if dim.history == "SCD2" and model.scd_type != "SCD2":
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message=f"{model.name} must be SCD2 per ArchitectureDecision",
                    model_name=model.name,
                )
            )
        uses_source_intervals = model.history_strategy == "source_validity_intervals"
        if dim.strategy == "source_validity_intervals" and not uses_source_intervals:
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message=f"{model.name} must use source validity intervals",
                    model_name=model.name,
                )
            )
        snapshot_strategies = {"snapshot_timestamp", "snapshot_check"}
        if (
            dim.strategy in snapshot_strategies
            and model.history_strategy not in snapshot_strategies
        ):
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message=f"{model.name} must use a snapshot SCD2 strategy",
                    model_name=model.name,
                )
            )
        if dim.strategy == "source_validity_intervals" and model.history_strategy in {
            "snapshot_timestamp",
            "snapshot_check",
        }:
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message="snapshot strategy used where source history exists",
                    model_name=model.name,
                )
            )
        if dim.history == "SCD2" and not model.tracked_scd2_columns and not dim.source_history:
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message=f"{model.name} SCD2 requires tracked columns",
                    model_name=model.name,
                )
            )
        if dim.history == "STATIC" and model.history_strategy not in {"static", None}:
            violations.append(
                DesignViolation(
                    code="SCD2_STRATEGY_INVALID",
                    message=f"{model.name} date dimension must be STATIC",
                    model_name=model.name,
                )
            )
    return violations


def _kinds(design: ModelDesign) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    allowed = {"STAGING", "INTERMEDIATE", "DIMENSION", "FACT", "MART", "SNAPSHOT"}
    for model in design.models:
        if model.model_kind in VAULT_KINDS:
            violations.append(
                DesignViolation(
                    code="DATA_VAULT_GENERATION_REJECTED",
                    message=f"{model.name} has Data Vault kind {model.model_kind}",
                    model_name=model.name,
                )
            )
        elif model.model_kind not in allowed:
            violations.append(
                DesignViolation(
                    code="UNSUPPORTED_MODEL_KIND",
                    message=f"{model.model_kind} is not supported in V1",
                    model_name=model.name,
                )
            )
    return violations


def _pii(design: ModelDesign) -> list[DesignViolation]:
    violations: list[DesignViolation] = []
    payload = design.model_dump(mode="json")

    def walk(value: object, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")
            return
        if isinstance(value, str) and "***" not in value:
            if _EMAIL_RE.search(value):
                violations.append(
                    DesignViolation(
                        code="PII_SAMPLE_EXPOSED",
                        message=f"raw email-like value at {path}",
                    )
                )
            elif _PHONE_RE.match(value) and not re.match(r"^\d{4}-\d{2}-\d{2}", value):
                violations.append(
                    DesignViolation(
                        code="PII_SAMPLE_EXPOSED",
                        message=f"raw phone-like value at {path}",
                    )
                )

    walk(payload, "$")
    for model in design.models:
        for column in model.columns:
            if column.is_pii and column.pii_handling is None:
                violations.append(
                    DesignViolation(
                        code="PII_SAMPLE_EXPOSED",
                        message=f"PII column {column.name} lacks handling metadata",
                        model_name=model.name,
                    )
                )
    return violations
