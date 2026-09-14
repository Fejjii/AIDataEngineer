"""Deterministic modelling signal extraction. Unknown stays UNKNOWN."""

from __future__ import annotations

from aide.capabilities.io import (
    AssetProfileEvidence,
    AuditabilitySignal,
    ChangeFrequency,
    CostSensitivity,
    DownstreamConsumer,
    DuplicateEvidenceLite,
    DuplicateGrainEvidence,
    EntityHistorySignal,
    IdentifierAlignment,
    KeyQuality,
    LatencyRequirement,
    ModellingSignals,
    PlatformCapabilities,
    QueryPattern,
    RelationshipCandidate,
    RequirementSpec,
    SourceStructure,
    TernaryFlag,
    VelocityClass,
    VolumeClass,
)
from aide.domain.sql import AssetRef
from aide.modelling.constants import (
    AUDIT_HIGH_HINTS,
    AUDIT_LOW_HINTS,
    COST_HIGH_HINTS,
    COST_LOW_HINTS,
    IDENTIFIER_ALIGNED,
    IDENTIFIER_PARTIAL,
    IDENTITY_COLUMN_HINTS,
    VOLUME_L_MIN,
    VOLUME_M_MIN,
    VOLUME_XL_MIN,
)
from aide.modelling.context import ModellingContext
from aide.modelling.platform import platform_capabilities_for


def classify_volume(row_count: int) -> VolumeClass:
    if row_count < VOLUME_M_MIN:
        return "S"
    if row_count < VOLUME_L_MIN:
        return "M"
    if row_count < VOLUME_XL_MIN:
        return "L"
    return "XL"


def classify_identifier_alignment(ratio: float) -> IdentifierAlignment:
    if ratio >= IDENTIFIER_ALIGNED:
        return "ALIGNED"
    if ratio >= IDENTIFIER_PARTIAL:
        return "PARTIAL"
    return "MISALIGNED"


def extract_modelling_signals(
    requirement: RequirementSpec,
    *,
    selected: tuple[AssetRef, ...],
    profiles: tuple[AssetProfileEvidence, ...] = (),
    relationships: tuple[RelationshipCandidate, ...] = (),
    duplicates: tuple[DuplicateEvidenceLite, ...] = (),
    context: ModellingContext | None = None,
    platform: PlatformCapabilities | None = None,
) -> ModellingSignals:
    ctx = context or ModellingContext()
    unknown: list[str] = []
    deliverable = requirement.deliverable_type
    history = requirement.history_requirements
    auditability = _auditability(requirement, ctx)
    if auditability == "UNKNOWN":
        unknown.append("auditability")
    source_count = len(selected) if selected else None
    schemas = tuple(sorted({asset.address[1] for asset in selected if len(asset.address) >= 2}))
    source_system_count = len(schemas) if selected else None
    if source_count is None:
        unknown.append("source_count")
    volume_row_count = _volume_row_count(selected, profiles, ctx)
    volume_class: VolumeClass = "UNKNOWN"
    if volume_row_count is None:
        unknown.append("volume_class")
    else:
        volume_class = classify_volume(volume_row_count)
    velocity, latency = _freshness(requirement.freshness_requirement)
    if velocity == "UNKNOWN":
        unknown.append("velocity")
    if latency == "UNKNOWN":
        unknown.append("latency_requirement")
    consumers = _consumers(requirement.consumers)
    patterns = _query_patterns(requirement, consumers)
    platform_caps = platform or platform_capabilities_for(
        vendor=ctx.vendor,
        dialect=ctx.dialect,
        platform_type=next((item.platform_type for item in selected if item.platform_type), None),
    )
    if platform_caps.supports_merge == "UNKNOWN":
        unknown.append("platform_capabilities")
    cost = _cost_sensitivity(requirement, ctx)
    if cost == "UNKNOWN":
        unknown.append("cost_sensitivity")
    entity_history = _entity_history(selected, profiles)
    global_history = _global_entity_history(entity_history)
    change = _change_frequency(profiles, entity_history)
    if change == "UNKNOWN":
        unknown.append("change_frequency")
    key_quality, grains = _key_quality(profiles, duplicates)
    if key_quality == "UNKNOWN":
        unknown.append("key_quality")
    alignment, ratio = _identifier_alignment(relationships)
    if alignment == "UNKNOWN":
        unknown.append("identifier_alignment")
    structure = _source_structure(profiles)
    if structure == "UNKNOWN":
        unknown.append("source_structure")
    return ModellingSignals(
        deliverable_type=deliverable,
        history_requirements=history,
        auditability=auditability,
        source_count=source_count,
        source_system_count=source_system_count,
        source_structure=structure,
        volume_class=volume_class,
        volume_row_count=volume_row_count,
        velocity=velocity,
        change_frequency=change,
        entity_history_in_source=global_history,
        entity_history=entity_history,
        query_patterns=patterns,
        downstream_consumers=consumers,
        latency_requirement=latency,
        platform_capabilities=platform_caps,
        cost_sensitivity=cost,
        key_quality=key_quality,
        identifier_alignment=alignment,
        identifier_alignment_ratio=ratio,
        duplicate_grains=grains,
        unknown_reasons=tuple(unknown),
    )


def with_duplicate_evidence(
    signals: ModellingSignals,
    duplicates: tuple[DuplicateEvidenceLite, ...],
    profiles: tuple[AssetProfileEvidence, ...] = (),
) -> ModellingSignals:
    """Fill duplicate grains from evidence when the caller supplied signals without them."""
    if not duplicates or signals.duplicate_grains:
        return signals
    key_quality, grains = _key_quality(profiles, duplicates)
    if not grains:
        return signals
    return signals.model_copy(
        update={
            "duplicate_grains": grains,
            "key_quality": (
                key_quality if signals.key_quality == "UNKNOWN" else "DUPLICATES_PRESENT"
            ),
        }
    )


def _contains_hint(values: tuple[str, ...], hints: tuple[str, ...]) -> bool:
    joined = " ".join(values).lower()
    return any(hint in joined for hint in hints)


def _auditability(requirement: RequirementSpec, ctx: ModellingContext) -> AuditabilitySignal:
    if ctx.org.auditability != "UNKNOWN":
        return ctx.org.auditability
    if _contains_hint(requirement.constraints, AUDIT_LOW_HINTS):
        return "LOW"
    if _contains_hint(requirement.constraints, AUDIT_HIGH_HINTS):
        return "HIGH"
    return "UNKNOWN"


def _cost_sensitivity(requirement: RequirementSpec, ctx: ModellingContext) -> CostSensitivity:
    if ctx.org.cost_sensitivity != "UNKNOWN":
        return ctx.org.cost_sensitivity
    if _contains_hint(requirement.constraints, COST_LOW_HINTS):
        return "LOW"
    if _contains_hint(requirement.constraints, COST_HIGH_HINTS):
        return "HIGH"
    return "UNKNOWN"


def _freshness(text: str | None) -> tuple[VelocityClass, LatencyRequirement]:
    if text is None or not text.strip():
        return "UNKNOWN", "UNKNOWN"
    token = text.lower()
    if any(item in token for item in ("minute", "real-time", "realtime", "streaming")):
        return "NEAR_REAL_TIME", "MINUTES"
    if any(item in token for item in ("hour", "intra")):
        return "INTRA_DAY", "HOURLY"
    if any(item in token for item in ("day", "daily", "batch")):
        return "BATCH_DAILY", "DAILY"
    return "UNKNOWN", "UNKNOWN"


def _consumers(raw: tuple[str, ...]) -> tuple[DownstreamConsumer, ...]:
    if not raw:
        return ("UNKNOWN",)
    mapped: list[DownstreamConsumer] = []
    for item in raw:
        token = item.strip().lower()
        if token in {"bi", "looker", "tableau", "powerbi", "dashboard"}:
            mapped.append("BI")
        elif token in {"ml", "machine learning", "features", "feature store"}:
            mapped.append("ML")
        elif token in {"application", "app", "api", "operational"}:
            mapped.append("APPLICATION")
        elif "sql" in token or "analyst" in token:
            mapped.append("ANALYSTS_SQL")
        else:
            mapped.append("UNKNOWN")
    unique = tuple(dict.fromkeys(mapped))
    if unique == ("UNKNOWN",) or not unique:
        return ("UNKNOWN",)
    return tuple(item for item in unique if item != "UNKNOWN") or ("UNKNOWN",)


def _query_patterns(
    requirement: RequirementSpec, consumers: tuple[DownstreamConsumer, ...]
) -> tuple[QueryPattern, ...]:
    patterns: list[QueryPattern] = []
    blob = " ".join(
        (
            requirement.goal,
            " ".join(requirement.consumers),
            " ".join(item.name for item in requirement.metrics),
        )
    ).lower()
    if "BI" in consumers:
        patterns.append("AGGREGATE_BI")
    if "drill" in blob:
        patterns.append("DRILL_DOWN")
    if "ML" in consumers or "feature" in blob:
        patterns.append("ML_FEATURES")
    if "APPLICATION" in consumers or "lookup" in blob:
        patterns.append("OPERATIONAL_LOOKUP")
    if not patterns:
        return ("UNKNOWN",)
    return tuple(dict.fromkeys(patterns))


def _volume_row_count(
    selected: tuple[AssetRef, ...],
    profiles: tuple[AssetProfileEvidence, ...],
    ctx: ModellingContext,
) -> int | None:
    catalog = dict(ctx.catalog_row_counts)
    counts: list[int] = []
    by_address = {item.asset.address: item for item in profiles}
    assets = selected or tuple(item.asset for item in profiles)
    for asset in assets:
        if asset.address in catalog:
            counts.append(catalog[asset.address])
        elif asset.address in by_address:
            counts.append(by_address[asset.address].row_count)
    if not counts and profiles:
        counts = [item.row_count for item in profiles]
    if not counts:
        return None
    return max(counts)


def _entity_name(asset: AssetRef) -> str:
    table = asset.address[-1].lower() if asset.address else "unknown"
    mapping = {
        "accounts": "customer",
        "customers": "customer",
        "invoice_lines": "invoice_line",
        "invoices": "invoice",
        "payments": "payment",
        "refunds": "refund",
        "plans": "plan",
        "subscriptions": "subscription",
        "contacts": "contact",
        "account_crosswalk": "customer_crosswalk",
    }
    return mapping.get(table, table.rstrip("s"))


def _entity_history(
    selected: tuple[AssetRef, ...],
    profiles: tuple[AssetProfileEvidence, ...],
) -> tuple[EntityHistorySignal, ...]:
    by_address = {item.asset.address: item for item in profiles}
    assets = selected or tuple(item.asset for item in profiles)
    items: list[EntityHistorySignal] = []
    for asset in assets:
        profile = by_address.get(asset.address)
        if profile is None:
            items.append(
                EntityHistorySignal(
                    entity=_entity_name(asset),
                    asset=asset,
                    has_source_history="UNKNOWN",
                )
            )
            continue
        has_history = profile.has_valid_from and profile.has_valid_to
        validity = []
        if profile.has_valid_from:
            validity.append("VALID_FROM")
        if profile.has_valid_to:
            validity.append("VALID_TO")
        items.append(
            EntityHistorySignal(
                entity=_entity_name(asset),
                asset=asset,
                has_source_history="TRUE" if has_history else "FALSE",
                validity_columns=tuple(validity),
            )
        )
    return tuple(items)


def _global_entity_history(items: tuple[EntityHistorySignal, ...]) -> TernaryFlag:
    if not items:
        return "UNKNOWN"
    if any(item.has_source_history == "TRUE" for item in items):
        return "TRUE"
    if all(item.has_source_history == "FALSE" for item in items):
        return "FALSE"
    if any(item.has_source_history == "UNKNOWN" for item in items) and not any(
        item.has_source_history == "TRUE" for item in items
    ):
        return "UNKNOWN"
    return "FALSE"


def _change_frequency(
    profiles: tuple[AssetProfileEvidence, ...],
    entity_history: tuple[EntityHistorySignal, ...],
) -> ChangeFrequency:
    if any(item.has_source_history == "TRUE" for item in entity_history) or any(
        item.has_valid_from and item.has_valid_to for item in profiles
    ):
        return "HIGH"
    if any(item.has_updated_at for item in profiles):
        return "MEDIUM"
    if any(item.has_created_at for item in profiles) and profiles:
        return "LOW"
    if not profiles:
        return "UNKNOWN"
    return "UNKNOWN"


def _key_quality(
    profiles: tuple[AssetProfileEvidence, ...],
    duplicates: tuple[DuplicateEvidenceLite, ...],
) -> tuple[KeyQuality, tuple[DuplicateGrainEvidence, ...]]:
    grains: list[DuplicateGrainEvidence] = []
    for item in duplicates:
        if item.extra_row_estimate > 0 or item.uniqueness_ratio < 1.0:
            grains.append(
                DuplicateGrainEvidence(
                    entity=_entity_name(item.asset),
                    asset=item.asset,
                    columns=item.columns,
                    uniqueness_ratio=item.uniqueness_ratio,
                    duplicate_groups_estimate=item.duplicate_groups_estimate,
                    extra_row_estimate=item.extra_row_estimate,
                    reason=item.reason,
                )
            )
    if not profiles:
        return "UNKNOWN", tuple(grains)
    if grains:
        return "DUPLICATES_PRESENT", tuple(grains)
    if all(not item.candidate_keys for item in profiles):
        return "NO_NATURAL_KEY", ()
    return "CLEAN", ()


_CUSTOMER_IDENTIFIER_TABLES = frozenset({"ACCOUNTS", "CUSTOMERS"})


def _identifier_alignment(
    relationships: tuple[RelationshipCandidate, ...],
) -> tuple[IdentifierAlignment, float | None]:
    """Classify cross-system identifier alignment without guessing.

    Prefer inclusion of operational customer keys *into* a crosswalk. Reverse
    coverage from the mapping table is expected to be lower when CRM duplicates
    or unmatched accounts exist, and must not flip PARTIAL to MISALIGNED.
    """
    inbound_customer: list[float] = []
    inbound_crosswalk: list[float] = []
    identity_ratios: list[float] = []
    for item in relationships:
        if not _is_cross_system(item.from_asset, item.to_asset):
            continue
        if not _is_identity_relationship(item):
            continue
        identity_ratios.append(item.inclusion_ratio)
        to_crosswalk = _is_crosswalk(item.to_asset)
        from_crosswalk = _is_crosswalk(item.from_asset)
        if to_crosswalk and not from_crosswalk:
            inbound_crosswalk.append(item.inclusion_ratio)
            if _table(item.from_asset) in _CUSTOMER_IDENTIFIER_TABLES:
                inbound_customer.append(item.inclusion_ratio)
    chosen = inbound_customer or inbound_crosswalk or identity_ratios
    if not chosen:
        return "UNKNOWN", None
    ratio = min(chosen)
    return classify_identifier_alignment(ratio), ratio


def _is_cross_system(left: AssetRef, right: AssetRef) -> bool:
    left_schema = _schema(left)
    right_schema = _schema(right)
    if left_schema is None or right_schema is None:
        return False
    return left_schema != right_schema


def _is_identity_relationship(item: RelationshipCandidate) -> bool:
    columns = item.from_columns + item.to_columns
    return any(any(hint in column.upper() for hint in IDENTITY_COLUMN_HINTS) for column in columns)


def _schema(asset: AssetRef) -> str | None:
    if len(asset.address) >= 3:
        return asset.address[1]
    if len(asset.address) >= 2:
        return asset.address[0]
    return None


def _table(asset: AssetRef) -> str:
    return asset.address[-1].upper() if asset.address else ""


def _is_crosswalk(asset: AssetRef) -> bool:
    return "CROSSWALK" in _table(asset)


def selected_has_crosswalk(selected: tuple[AssetRef, ...]) -> bool:
    return any(_is_crosswalk(asset) for asset in selected)


def _source_structure(profiles: tuple[AssetProfileEvidence, ...]) -> SourceStructure:
    if not profiles:
        return "UNKNOWN"
    eventish = sum(
        1
        for item in profiles
        if any(token in item.asset.address[-1].upper() for token in ("EVENT", "LOG"))
    )
    if eventish == len(profiles):
        return "EVENT_LOG"
    avg_cols = sum(len(item.columns) for item in profiles) / max(len(profiles), 1)
    if eventish and eventish < len(profiles):
        return "MIXED"
    if len(profiles) >= 3 and avg_cols <= 24:
        return "NORMALIZED_3NF"
    if len(profiles) <= 2 and avg_cols >= 25:
        return "DENORMALIZED_EXTRACT"
    if len(profiles) >= 3:
        return "NORMALIZED_3NF"
    return "UNKNOWN"
