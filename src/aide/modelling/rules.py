"""Deterministic first-match modelling rule table. No LLM."""

from __future__ import annotations

from aide.capabilities.io import (
    AssetProfileEvidence,
    DedupDecision,
    DimensionDecision,
    FactDecision,
    IntegrationLayerDecision,
    LayeringDecision,
    MaterializationDecision,
    ModellingOpenQuestion,
    ModellingSignals,
    PresentationDecision,
    RequirementSpec,
)
from aide.domain.sql import AssetRef
from aide.modelling.constants import (
    APPROVAL_MODEL_COUNT,
    CHANGE_RANK,
    FACT_TABLE_HINTS,
    LATENCY_RANK,
    MEASURE_COLUMN_HINTS,
    VOLUME_RANK,
    WATERMARK_LOOKBACK_DAYS,
    WATERMARK_NULL_MAX,
)
from aide.modelling.context import ModellingContext
from aide.modelling.signals import selected_has_crosswalk


def change_at_least(signals: ModellingSignals, minimum: str) -> bool:
    rank = CHANGE_RANK.get(signals.change_frequency)
    needed = CHANGE_RANK.get(minimum)
    if rank is None or needed is None:
        return False
    return rank >= needed


def volume_at_least(signals: ModellingSignals, minimum: str) -> bool:
    rank = VOLUME_RANK.get(signals.volume_class)
    needed = VOLUME_RANK.get(minimum)
    if rank is None or needed is None:
        return False
    return rank >= needed


def latency_at_most(signals: ModellingSignals, maximum: str) -> bool:
    rank = LATENCY_RANK.get(signals.latency_requirement)
    needed = LATENCY_RANK.get(maximum)
    if rank is None or needed is None:
        return False
    return rank <= needed


def decide_layering(
    signals: ModellingSignals, context: ModellingContext
) -> tuple[LayeringDecision, tuple[ModellingOpenQuestion, ...]]:
    naming = context.org.naming_convention
    if signals.deliverable_type in {"ANALYTICAL_DATA_PRODUCT", "PIPELINE"}:
        return LayeringDecision(decision="STAGING_INTERMEDIATE_MARTS", rule="L1", naming=naming), ()
    if signals.deliverable_type == "MODEL_CHANGE":
        if context.existing_layering is None:
            return (
                LayeringDecision(decision="REUSE_EXISTING", rule="L2", naming=naming),
                (
                    ModellingOpenQuestion(
                        topic="existing_layering",
                        question="MODEL_CHANGE requires detected project layering",
                        blocking=True,
                        rule="L2",
                    ),
                ),
            )
        return LayeringDecision(decision="REUSE_EXISTING", rule="L2", naming=naming), ()
    if signals.deliverable_type == "QUALITY_SUITE":
        return LayeringDecision(decision="TESTS_ONLY", rule="L3", naming=naming), ()
    return LayeringDecision(decision="EPHEMERAL_QUERIES", rule="L4", naming=naming), ()


def decide_integration(signals: ModellingSignals) -> IntegrationLayerDecision:
    systems = signals.source_system_count
    if (
        signals.auditability == "HIGH"
        and systems is not None
        and systems >= 3
        and signals.history_requirements == "FULL_HISTORY"
        and change_at_least(signals, "MEDIUM")
    ):
        return IntegrationLayerDecision(
            decision="RAW_VAULT_RECOMMENDED",
            rule="V1",
            recommendation=(
                "Raw Vault is justified; V1 generates star schema only and records "
                "this recommendation"
            ),
        )
    if systems is not None and systems >= 5 and signals.identifier_alignment == "MISALIGNED":
        return IntegrationLayerDecision(
            decision="RAW_VAULT_RECOMMENDED",
            rule="V2",
            recommendation=(
                "Raw Vault is justified by misaligned identifiers across many systems; "
                "V1 generates star schema only"
            ),
        )
    return IntegrationLayerDecision(decision="NO_VAULT", rule="V3", recommendation=None)


def decide_presentation(
    signals: ModellingSignals, context: ModellingContext
) -> tuple[
    PresentationDecision,
    tuple[PresentationDecision, ...],
    tuple[ModellingOpenQuestion, ...],
]:
    questions: list[ModellingOpenQuestion] = []
    consumers = set(signals.downstream_consumers)
    patterns = set(signals.query_patterns)
    if "AGGREGATE_BI" in patterns or "DRILL_DOWN" in patterns or "BI" in consumers:
        primary = PresentationDecision(decision="STAR_SCHEMA", rule="P1")
    elif "ML" in consumers and "ML_FEATURES" in patterns:
        primary = PresentationDecision(decision="WIDE_FEATURE_TABLE", rule="P2")
        questions.append(
            ModellingOpenQuestion(
                topic="wide_feature_table",
                question="V1 emits star schema plus one wide mart for ML features",
                blocking=False,
                rule="P2",
            )
        )
    elif "APPLICATION" in consumers and "OPERATIONAL_LOOKUP" in patterns:
        primary = PresentationDecision(decision="NORMALIZED_SERVING", rule="P3")
        questions.append(
            ModellingOpenQuestion(
                topic="normalized_serving",
                question="NORMALIZED_SERVING is a V2 pattern; V1 still emits a star schema",
                blocking=False,
                rule="P3",
            )
        )
    else:
        primary = PresentationDecision(decision="STAR_SCHEMA", rule="P5")
        questions.append(
            ModellingOpenQuestion(
                topic="consumers",
                question="Consumers are UNKNOWN; star schema chosen pending human confirmation",
                blocking=False,
                rule="P5",
            )
        )
    extras: list[PresentationDecision] = []
    for hint in context.dimension_hierarchies:
        if (
            len(hint.levels) > 3
            and hint.independent_change_rates
            and volume_at_least(signals, "L")
            and signals.cost_sensitivity == "HIGH"
        ):
            extras.append(
                PresentationDecision(decision="SNOWFLAKE_SCHEMA", rule="P4", dimension=hint.entity)
            )
    return primary, tuple(extras), tuple(questions)


def _table_name(asset: AssetRef) -> str:
    return asset.address[-1].upper() if asset.address else ""


def _is_fact_asset(asset: AssetRef, profile: AssetProfileEvidence | None) -> bool:
    name = _table_name(asset)
    fact_hints = ("INVOICE_LINES", "PAYMENTS", "REFUNDS")
    if any(hint in name.replace("_", "") or hint in name for hint in fact_hints):
        return True
    if any(hint in name for hint in FACT_TABLE_HINTS) and profile is not None:
        columns = {column.upper() for column in profile.columns}
        return bool(columns & MEASURE_COLUMN_HINTS)
    return False


def _fact_entity(asset: AssetRef) -> str:
    name = _table_name(asset)
    mapping = {
        "INVOICE_LINES": "invoice_line",
        "PAYMENTS": "payment",
        "REFUNDS": "refund",
        "ORDERS": "order",
    }
    return mapping.get(name, name.lower().rstrip("s"))


def _fact_grain(asset: AssetRef, profile: AssetProfileEvidence | None) -> tuple[str, ...]:
    name = _table_name(asset)
    defaults = {
        "INVOICE_LINES": ("invoice_line_id",),
        "PAYMENTS": ("payment_id",),
        "REFUNDS": ("refund_id",),
    }
    if name in defaults:
        return defaults[name]
    if profile is not None:
        for key in profile.candidate_keys:
            return tuple(column.lower() for column in key.columns)
        for columns, uniqueness, is_candidate in profile.composite_key_uniqueness:
            if is_candidate and uniqueness >= 0.999 and len(columns) == 1:
                return tuple(column.lower() for column in columns)
    return ()


def _watermark(profile: AssetProfileEvidence | None) -> tuple[str | None, bool]:
    if profile is None:
        return None, False
    if profile.has_updated_at and (
        profile.updated_at_null_ratio is None or profile.updated_at_null_ratio <= WATERMARK_NULL_MAX
    ):
        return "UPDATED_AT", True
    if profile.has_loaded_at and (
        profile.loaded_at_null_ratio is None or profile.loaded_at_null_ratio <= WATERMARK_NULL_MAX
    ):
        return "_LOADED_AT", True
    if profile.has_updated_at or profile.has_loaded_at:
        return ("UPDATED_AT" if profile.has_updated_at else "_LOADED_AT"), False
    return None, False


def decide_facts(
    signals: ModellingSignals,
    *,
    selected: tuple[AssetRef, ...],
    profiles: tuple[AssetProfileEvidence, ...],
    requirement: RequirementSpec,
) -> tuple[tuple[FactDecision, ...], tuple[DedupDecision, ...], tuple[str, ...]]:
    by_address = {item.asset.address: item for item in profiles}
    facts: list[FactDecision] = []
    dedup: list[DedupDecision] = []
    recommendations: list[str] = []
    merge = signals.platform_capabilities.supports_merge == "TRUE"
    for asset in selected:
        profile = by_address.get(asset.address)
        if not _is_fact_asset(asset, profile):
            continue
        entity = _fact_entity(asset)
        grain = _fact_grain(asset, profile)
        rules: list[str] = ["F1"]
        kind: str = "TRANSACTION_FACT"
        dup = next(
            (
                item
                for item in signals.duplicate_grains
                if (item.asset is not None and item.asset.address == asset.address)
                or item.entity == entity
            ),
            None,
        )
        dedup_required = dup is not None
        dedup_rule = None
        if dup is not None:
            rules.append("F4")
            if entity == "payment":
                dedup_rule = (
                    "qualify row_number() over (partition by invoice_id, payment_ref "
                    "order by _loaded_at desc) = 1"
                )
                dedup.append(
                    DedupDecision(
                        entity="payment",
                        grain=("invoice_id", "payment_ref"),
                        description=dedup_rule,
                    )
                )
            else:
                dedup_rule = f"deduplicate {entity} at grain {','.join(dup.columns)}"
                dedup.append(
                    DedupDecision(
                        entity=entity,
                        grain=tuple(column.lower() for column in dup.columns),
                        description=dedup_rule,
                    )
                )
        watermark, reliable = _watermark(profile)
        materialization, mat_rules = _fact_materialization(
            signals, merge=merge, watermark=watermark, reliable=reliable
        )
        rules.extend(mat_rules)
        facts.append(
            FactDecision(
                entity=entity,
                kind=kind,  # type: ignore[arg-type]
                grain=grain,
                source_assets=(asset,),
                materialization=materialization,  # type: ignore[arg-type]
                unique_key=grain,
                watermark_column=watermark if materialization == "incremental" else None,
                watermark_lookback_days=(
                    WATERMARK_LOOKBACK_DAYS if materialization == "incremental" else None
                ),
                dedup_required=dedup_required,
                dedup_rule=dedup_rule,
                rule=tuple(dict.fromkeys(rules)),
            )
        )
    metric_names = " ".join(item.name.lower() for item in requirement.metrics)
    metric_blob = metric_names + " " + requirement.goal.lower()
    needs_snapshot = any(token in metric_blob for token in ("mrr", "revenue", "balance"))
    if needs_snapshot and facts:
        snapshot_rules = ["F2"]
        mart_mat, snapshot_mat_rules = "table", ["M6"]
        supports_dt = signals.platform_capabilities.supports_dynamic_tables == "TRUE"
        if latency_at_most(signals, "HOURLY") and supports_dt:
            mart_mat = "dynamic_table"
        snapshot_rules.extend(snapshot_mat_rules)
        facts.append(
            FactDecision(
                entity="customer_revenue_daily",
                kind="PERIODIC_SNAPSHOT_FACT",
                grain=("customer_sk", "date_day"),
                source_assets=(),
                materialization=mart_mat,  # type: ignore[arg-type]
                unique_key=("customer_sk", "date_day"),
                watermark_column=None,
                watermark_lookback_days=None,
                dedup_required=False,
                dedup_rule=None,
                rule=tuple(snapshot_rules),
            )
        )
    milestone_entities = {item.entity for item in facts}
    if {"invoice_line", "payment"} <= milestone_entities and any(
        token in requirement.goal.lower() for token in ("order", "milestone")
    ):
        recommendations.append(
            "F3: accumulating snapshot fact is recommended for order→invoice→payment (V2 only)"
        )
    customer_dup = next(
        (
            item
            for item in signals.duplicate_grains
            if item.entity in {"customer", "account"}
            or (item.asset is not None and _table_name(item.asset) == "ACCOUNTS")
        ),
        None,
    )
    if customer_dup is not None:
        dedup.append(
            DedupDecision(
                entity="customer",
                grain=tuple(column.lower() for column in customer_dup.columns),
                description=(
                    "survivorship by latest UPDATED_AT within normalized WEBSITE_DOMAIN group, "
                    "excluding deleted accounts"
                ),
            )
        )
    return tuple(facts), tuple(dedup), tuple(recommendations)


def _fact_materialization(
    signals: ModellingSignals, *, merge: bool, watermark: str | None, reliable: bool
) -> tuple[str, tuple[str, ...]]:
    if signals.volume_class == "S":
        return "table", ("M4",)
    if volume_at_least(signals, "M") and reliable and merge and watermark is not None:
        return "incremental", ("M3",)
    if watermark is None or not reliable:
        return "table", ("M5",)
    return "table", ("M5",)


def _history_for_entity(
    signals: ModellingSignals, entity: str, source_assets: tuple[AssetRef, ...]
) -> tuple[DimensionDecision, tuple[ModellingOpenQuestion, ...]]:
    questions: list[ModellingOpenQuestion] = []
    matches = tuple(item for item in signals.entity_history if item.entity == entity)
    source_history = any(item.has_source_history == "TRUE" for item in matches)
    if signals.history_requirements == "UNKNOWN":
        questions.append(
            ModellingOpenQuestion(
                topic="history_requirements",
                question="History requirement is UNKNOWN; SCD2 vs SCD1 is blocked on clarification",
                blocking=True,
                rule="D4",
            )
        )
        return (
            DimensionDecision(
                entity=entity,
                history="SCD1",
                source_history=source_history,
                strategy="none",
                source_assets=source_assets,
                rule=("D4",),
            ),
            tuple(questions),
        )
    if signals.history_requirements == "CURRENT_ONLY":
        return (
            DimensionDecision(
                entity=entity,
                history="SCD1",
                source_history=source_history,
                strategy="none",
                source_assets=source_assets,
                rule=("D3",),
            ),
            (),
        )
    rules: list[str] = []
    if change_at_least(signals, "MEDIUM") or source_history:
        rules.append("D1")
    else:
        rules.append("D2")
    if source_history:
        rules.append("D6")
        strategy = "source_validity_intervals"
    else:
        rules.append("D7")
        strategy = "snapshot_timestamp"
    return (
        DimensionDecision(
            entity=entity,
            history="SCD2",
            source_history=source_history,
            strategy=strategy,  # type: ignore[arg-type]
            source_assets=source_assets,
            tracked_columns=(),
            rule=tuple(rules),
        ),
        tuple(questions),
    )


def decide_dimensions(
    signals: ModellingSignals,
    *,
    selected: tuple[AssetRef, ...],
    layering_rule: str,
    context: ModellingContext | None = None,
) -> tuple[tuple[DimensionDecision, ...], tuple[ModellingOpenQuestion, ...]]:
    if layering_rule in {"L3", "L4"}:
        return (), ()
    ctx = context or ModellingContext()
    by_table = {_table_name(asset): asset for asset in selected}
    questions: list[ModellingOpenQuestion] = []
    dims: list[DimensionDecision] = []
    customer_tables = {"ACCOUNTS", "CUSTOMERS", "ACCOUNT_CROSSWALK"}
    customer_assets = tuple(asset for table, asset in by_table.items() if table in customer_tables)
    if customer_assets:
        dim, extra = _history_for_entity(signals, "customer", customer_assets)
        questions.extend(extra)
        dims.append(_apply_d5(dim, ctx))
    if "PLANS" in by_table:
        dim, extra = _history_for_entity(signals, "plan", (by_table["PLANS"],))
        questions.extend(extra)
        dims.append(_apply_d5(dim, ctx))
    dims.append(
        DimensionDecision(
            entity="date",
            history="STATIC",
            source_history=False,
            strategy="static",
            source_assets=(),
            rule=("D8",),
        )
    )
    if signals.identifier_alignment == "MISALIGNED":
        derivable = selected_has_crosswalk(selected)
        questions.append(
            ModellingOpenQuestion(
                topic="survivorship",
                question=(
                    "Identifier alignment is MISALIGNED; propose survivorship using the crosswalk"
                    if derivable
                    else (
                        "Identifier alignment is MISALIGNED; a human survivorship rule is required"
                    )
                ),
                blocking=not derivable,
                rule="conformance",
            )
        )
    return tuple(dims), tuple(questions)


def _apply_d5(dim: DimensionDecision, context: ModellingContext) -> DimensionDecision:
    attrs = tuple(
        attr for entity, attr in context.low_value_scd1_attributes if entity == dim.entity
    )
    if not attrs or dim.history != "SCD2":
        return dim
    return dim.model_copy(
        update={
            "hybrid_scd1_attributes": attrs,
            "rule": tuple(dict.fromkeys((*dim.rule, "D5"))),
        }
    )


def decide_materialization(
    signals: ModellingSignals,
    *,
    facts: tuple[FactDecision, ...],
) -> tuple[MaterializationDecision, ...]:
    items: list[MaterializationDecision] = []
    staging_mat = "view" if signals.volume_class in {"S", "M", "UNKNOWN"} else "table"
    items.append(
        MaterializationDecision(
            target="staging",
            materialization=staging_mat,  # type: ignore[arg-type]
            rule="M1",
            detail="staging is 1:1 cleaned sources",
        )
    )
    items.append(
        MaterializationDecision(
            target="intermediate",
            materialization="table",
            rule="M2",
            detail=(
                "intermediate tables for dedup and conformance; ephemeral only if referenced "
                "once at S volume, which is not proven here"
            ),
        )
    )
    seen_fact_rules: set[str] = set()
    for fact in facts:
        for rule in fact.rule:
            if rule in {"M3", "M4", "M5", "M6"} and rule not in seen_fact_rules:
                seen_fact_rules.add(rule)
                items.append(
                    MaterializationDecision(
                        target=fact.entity,
                        materialization=fact.materialization,
                        rule=rule,  # type: ignore[arg-type]
                        detail=f"{fact.kind} materialization",
                    )
                )
    if not any(item.rule == "M6" for item in items):
        mart_mat = "table"
        supports_dt = signals.platform_capabilities.supports_dynamic_tables == "TRUE"
        if latency_at_most(signals, "HOURLY") and supports_dt:
            mart_mat = "dynamic_table"
        items.append(
            MaterializationDecision(
                target="marts",
                materialization=mart_mat,  # type: ignore[arg-type]
                rule="M6",
                detail=("marts are tables unless hourly latency and dynamic tables are supported"),
            )
        )
    if signals.cost_sensitivity == "HIGH" and volume_at_least(signals, "L"):
        items.append(
            MaterializationDecision(
                target="facts",
                materialization="table",
                rule="M7",
                detail=(
                    "clustering key recommendation on fact date column (recommendation only in V1)"
                ),
            )
        )
    return tuple(items)


def estimate_model_count(
    *,
    selected_count: int,
    facts: tuple[FactDecision, ...],
    dimensions: tuple[DimensionDecision, ...],
    dedup: tuple[DedupDecision, ...],
    layering_rule: str,
) -> int:
    if layering_rule == "L4":
        return 0
    if layering_rule == "L3":
        return 0
    staging = selected_count
    interval_strategy = "source_validity_intervals"
    snapshot_strategies = {"snapshot_timestamp", "snapshot_check"}
    intermediates = len(dedup) + sum(1 for item in dimensions if item.strategy == interval_strategy)
    snapshots = sum(1 for item in dimensions if item.strategy in snapshot_strategies)
    marts = sum(1 for item in facts if item.kind == "PERIODIC_SNAPSHOT_FACT")
    transaction_facts = sum(1 for item in facts if item.kind == "TRANSACTION_FACT")
    return staging + intermediates + snapshots + len(dimensions) + transaction_facts + marts


def approval_flags(
    *,
    integration: IntegrationLayerDecision,
    extras: tuple[PresentationDecision, ...],
    estimated_model_count: int,
    estimated_cost_class: str,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if integration.rule in {"V1", "V2"}:
        reasons.append(integration.rule)
    if any(item.rule == "P4" for item in extras):
        reasons.append("P4")
    if estimated_model_count > APPROVAL_MODEL_COUNT:
        reasons.append("model_count")
    if estimated_cost_class in {"L", "XL"}:
        reasons.append("cost_class")
    return bool(reasons), tuple(reasons)
