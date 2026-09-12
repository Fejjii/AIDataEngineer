"""PROFILING phase templates and deterministic task ordering."""

from __future__ import annotations

from typing import Any

from aide.capabilities.io import (
    Budget,
    InferRelationshipsInput,
    Plan,
    PlannedTask,
    ProfileDatasetInput,
    SampleDatasetInput,
)
from aide.capabilities.v1_kernel import kernel_registry
from aide.domain.sql import AssetKind, AssetRef
from aide.domain.states import WorkflowState
from aide.domain.tasks import TaskTemplate
from aide.orchestration.materialization import TemplateSpec
from aide.profiling.budgets import TINY_OFFLINE_BUDGET, ProfilingBudget
from aide.profiling.engine import sample_assets_for
from aide.profiling.fixtures import CONNECTOR_ID, DEMO_SELECTED_ADDRESSES, asset_slug

PROFILING_EXIT_CRITERIA: tuple[str, ...] = (
    "dataset_profiles",
    "relationship_candidates",
    "profiling_summary",
)


def selected_asset_refs(
    addresses: tuple[tuple[str, str, str], ...] = DEMO_SELECTED_ADDRESSES,
    *,
    connector_id: str = CONNECTOR_ID,
) -> tuple[AssetRef, ...]:
    ordered = tuple(sorted(addresses))
    return tuple(
        AssetRef(
            connector_id=connector_id,
            address=address,
            kind=AssetKind.TABLE,
            platform_type="snowflake",
        )
        for address in ordered
    )


def profile_local_id(asset: AssetRef) -> str:
    return f"p_{asset_slug(asset)}"


def infer_local_id() -> str:
    return "r_infer_relationships"


def sample_local_id(asset: AssetRef) -> str:
    return f"s_{asset_slug(asset)}"


def _capability_timeout(capability_id: str) -> tuple[int, int]:
    spec = kernel_registry().get(capability_id, 1)
    return spec.timeout_seconds, spec.retry.max_attempts


def build_profiling_templates(
    selected: tuple[AssetRef, ...],
    *,
    budget: ProfilingBudget | None = None,
    max_tasks: int = 50,
    connector_id: str = CONNECTOR_ID,
) -> tuple[TemplateSpec, ...]:
    """Create bounded, sorted PROFILING templates. Profiles selected assets only."""
    limits = budget or TINY_OFFLINE_BUDGET
    assets = tuple(sorted(selected, key=lambda item: item.address))
    if max_tasks < 2:
        raise ValueError("PROFILING requires at least one profile task and infer_relationships")
    sample_limit = min(limits.sample_asset_limit, len(assets))
    profile_slots = max_tasks - 1 - sample_limit
    if profile_slots < 1:
        sample_limit = max(0, max_tasks - 1)
        profile_slots = max_tasks - 1 - sample_limit
    profile_assets = assets[:profile_slots]
    sample_pool = sample_assets_for(profile_assets, limit=sample_limit)
    profile_timeout, profile_attempts = _capability_timeout("profile_dataset")
    infer_timeout, infer_attempts = _capability_timeout("infer_relationships")
    sample_timeout, sample_attempts = _capability_timeout("sample_dataset")
    cap_budget: Budget = limits.capability_budget()
    templates: list[TemplateSpec] = []
    profile_ids = tuple(profile_local_id(asset) for asset in profile_assets)
    for asset in profile_assets:
        payload = ProfileDatasetInput(
            asset=asset,
            budget=cap_budget,
            top_k=limits.top_k,
        ).model_dump(mode="json")
        templates.append(
            TemplateSpec(
                local_id=profile_local_id(asset),
                capability_id="profile_dataset",
                capability_contract_version=1,
                connector_id=connector_id,
                depends_on=(),
                required_dependencies=(),
                unresolved_inputs=payload,
                timeout_seconds=profile_timeout,
                max_attempts=profile_attempts,
            )
        )
    infer_payload = InferRelationshipsInput(
        assets=profile_assets,
        max_pairs=limits.max_pairs,
        budget=cap_budget,
    ).model_dump(mode="json")
    templates.append(
        TemplateSpec(
            local_id=infer_local_id(),
            capability_id="infer_relationships",
            capability_contract_version=1,
            connector_id=connector_id,
            depends_on=profile_ids,
            required_dependencies=profile_ids,
            unresolved_inputs=infer_payload,
            timeout_seconds=infer_timeout,
            max_attempts=infer_attempts,
        )
    )
    for asset in sample_pool:
        sample_n = min(limits.sample_n, 20)
        payload = SampleDatasetInput(asset=asset, n=sample_n).model_dump(mode="json")
        templates.append(
            TemplateSpec(
                local_id=sample_local_id(asset),
                capability_id="sample_dataset",
                capability_contract_version=1,
                connector_id=connector_id,
                depends_on=(profile_local_id(asset),),
                required_dependencies=(profile_local_id(asset),),
                unresolved_inputs=payload,
                timeout_seconds=sample_timeout,
                max_attempts=sample_attempts,
            )
        )
    ordered = tuple(sorted(templates, key=lambda item: item.local_id))
    return ordered


def build_profiling_plan(
    selected: tuple[AssetRef, ...],
    *,
    budget: ProfilingBudget | None = None,
    max_tasks: int = 50,
    connector_id: str = CONNECTOR_ID,
) -> Plan:
    templates = build_profiling_templates(
        selected, budget=budget, max_tasks=max_tasks, connector_id=connector_id
    )
    tasks = tuple(
        PlannedTask(
            local_id=item.local_id,
            capability_id=item.capability_id,
            connector_id=item.connector_id,
            depends_on=item.depends_on,
            inputs=item.unresolved_inputs,
            rationale=_rationale(item.capability_id),
        )
        for item in templates
    )
    return Plan(
        phase=WorkflowState.PROFILING,
        tasks=tasks,
        phase_exit_criteria=PROFILING_EXIT_CRITERIA,
        assumptions=(
            "selected assets only; excluded opportunities/tickets are not profiled",
            "PII is masked before sample persistence",
            "query and sample budgets are explicit",
        ),
    )


def templates_to_task_templates(
    specs: tuple[TemplateSpec, ...],
    *,
    phase_run_id: Any,
    template_ids: dict[str, Any],
) -> tuple[TaskTemplate, ...]:
    return tuple(
        TaskTemplate(
            template_id=template_ids[item.local_id],
            phase_run_id=phase_run_id,
            local_id=item.local_id,
            capability_id=item.capability_id,
            capability_contract_version=item.capability_contract_version,
            connector_id=item.connector_id,
            depends_on=item.depends_on,
            unresolved_inputs=item.unresolved_inputs,
            timeout_seconds=item.timeout_seconds,
            max_attempts=item.max_attempts,
        )
        for item in specs
    )


def _rationale(capability_id: str) -> str:
    return {
        "profile_dataset": "deterministic column statistics for modelling signals",
        "infer_relationships": "deterministic inclusion-dependency candidates",
        "sample_dataset": "bounded masked sample for later design reasoning",
    }.get(capability_id, capability_id)
