"""Deterministic modelling decision engine. The LLM never chooses the architecture class."""

from __future__ import annotations

from aide.capabilities.io import (
    ArchitectureDecision,
    AssetProfileEvidence,
    DedupDecision,
    DimensionDecision,
    DuplicateEvidenceLite,
    FactDecision,
    MaterializationDecision,
    ModellingSignals,
    RelationshipCandidate,
    RequirementSpec,
)
from aide.domain.sql import AssetRef
from aide.modelling.context import ModellingContext
from aide.modelling.evidence import evidence_from_run
from aide.modelling.rules import (
    approval_flags,
    decide_dimensions,
    decide_facts,
    decide_integration,
    decide_layering,
    decide_materialization,
    decide_presentation,
    estimate_model_count,
)
from aide.modelling.signals import extract_modelling_signals, with_duplicate_evidence
from aide.profiling.artifacts import ProfilingRunResult

RULE_FAMILY_ORDER = ("L", "V", "P", "F", "D", "M")


def _rule_sort_key(rule_id: str) -> tuple[int, str, int]:
    family = rule_id[:1]
    rest = rule_id[1:]
    family_rank = RULE_FAMILY_ORDER.index(family) if family in RULE_FAMILY_ORDER else 99
    number = int(rest) if rest.isdigit() else 0
    return family_rank, family, number


def collect_rule_ids(
    *,
    layering_rule: str,
    integration_rule: str,
    presentation_rule: str,
    extra_presentation_rules: tuple[str, ...],
    facts: tuple[FactDecision, ...],
    dimensions: tuple[DimensionDecision, ...],
    materialization: tuple[MaterializationDecision, ...],
    dedup: tuple[DedupDecision, ...],
) -> tuple[str, ...]:
    ids: list[str] = [layering_rule, integration_rule, presentation_rule, *extra_presentation_rules]
    for fact in facts:
        ids.extend(fact.rule)
    for dim in dimensions:
        ids.extend(dim.rule)
    for item in materialization:
        ids.append(item.rule)
    if dedup:
        ids.append("F4")
    unique = tuple(dict.fromkeys(ids))
    return tuple(sorted(unique, key=_rule_sort_key))


class ModellingDecisionEngine:
    def decide(
        self,
        requirement: RequirementSpec,
        *,
        selected: tuple[AssetRef, ...],
        run: ProfilingRunResult | None = None,
        profiles: tuple[AssetProfileEvidence, ...] = (),
        relationships: tuple[RelationshipCandidate, ...] = (),
        duplicates: tuple[DuplicateEvidenceLite, ...] = (),
        context: ModellingContext | None = None,
        signals: ModellingSignals | None = None,
    ) -> ArchitectureDecision:
        ctx = context or ModellingContext()
        if run is not None:
            profiles, relationships, duplicates, _summary = evidence_from_run(run)
            if not selected:
                selected = tuple(item.asset for item in profiles)
        resolved = signals or extract_modelling_signals(
            requirement,
            selected=selected,
            profiles=profiles,
            relationships=relationships,
            duplicates=duplicates,
            context=ctx,
        )
        resolved = with_duplicate_evidence(resolved, duplicates, profiles)
        layering, layering_questions = decide_layering(resolved, ctx)
        integration = decide_integration(resolved)
        presentation, extras, presentation_questions = decide_presentation(resolved, ctx)
        facts, dedup, fact_recommendations = decide_facts(
            resolved, selected=selected, profiles=profiles, requirement=requirement
        )
        dimensions, dimension_questions = decide_dimensions(
            resolved, selected=selected, layering_rule=layering.rule, context=ctx
        )
        materialization = decide_materialization(resolved, facts=facts)
        estimated = estimate_model_count(
            selected_count=len(selected),
            facts=facts,
            dimensions=dimensions,
            dedup=dedup,
            layering_rule=layering.rule,
        )
        approval_required, approval_reasons = approval_flags(
            integration=integration,
            extras=extras,
            estimated_model_count=estimated,
            estimated_cost_class=resolved.volume_class,
        )
        recommendations = list(fact_recommendations)
        if integration.recommendation:
            recommendations.append(integration.recommendation)
        if presentation.rule == "P2":
            recommendations.append("V1 emits star schema plus one wide feature mart")
        if any(item.rule == "P4" for item in extras):
            recommendations.append("Snowflake schema for a high-change hierarchy requires approval")
        if any(item.rule == "M5" for item in materialization):
            recommendations.append("Add a reliable source watermark to enable incremental facts")
        if any(item.rule == "M7" for item in materialization):
            recommendations.append("Cluster large facts on the date column")
        questions = layering_questions + presentation_questions + dimension_questions
        rule_ids = collect_rule_ids(
            layering_rule=layering.rule,
            integration_rule=integration.rule,
            presentation_rule=presentation.rule,
            extra_presentation_rules=tuple(item.rule for item in extras),
            facts=facts,
            dimensions=dimensions,
            materialization=materialization,
            dedup=dedup,
        )
        return ArchitectureDecision(
            signals=resolved,
            layering=layering,
            naming=layering.naming,
            integration_layer=integration,
            presentation=presentation,
            facts=facts,
            dimensions=dimensions,
            dedup=dedup,
            materialization=materialization,
            recommendations=tuple(recommendations),
            open_questions=questions,
            approval_required=approval_required,
            approval_reasons=approval_reasons,
            rule_ids=rule_ids,
            estimated_model_count=estimated,
            estimated_cost_class=resolved.volume_class,
        )


def decide_architecture(
    requirement: RequirementSpec,
    *,
    selected: tuple[AssetRef, ...],
    run: ProfilingRunResult | None = None,
    context: ModellingContext | None = None,
) -> ArchitectureDecision:
    return ModellingDecisionEngine().decide(
        requirement, selected=selected, run=run, context=context
    )
