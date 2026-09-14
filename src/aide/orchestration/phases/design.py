"""DESIGN phase templates and deterministic task ordering.

g1 (ModellingDecisionEngine.decide) is in-process deterministic work, not an LLM task.
g2_propose_model_design is the only templated reasoning capability in this phase.
"""

from __future__ import annotations

from typing import Any

from aide.capabilities.io import Plan, PlannedTask, ProposeModelDesignInput
from aide.capabilities.v1_kernel import kernel_registry
from aide.domain.states import WorkflowState
from aide.domain.tasks import TaskTemplate
from aide.orchestration.materialization import TemplateSpec

DESIGN_EXIT_CRITERIA: tuple[str, ...] = (
    "architecture_decision",
    "model_design",
    "design_validation_report",
)

PROPOSE_LOCAL_ID = "g2_propose_model_design"


def build_design_templates(
    payload: ProposeModelDesignInput | None = None,
) -> tuple[TemplateSpec, ...]:
    spec = kernel_registry().get("propose_model_design", 1)
    inputs: dict[str, object] = {}
    if payload is not None:
        inputs = payload.model_dump(mode="json")
    templates = (
        TemplateSpec(
            local_id=PROPOSE_LOCAL_ID,
            capability_id="propose_model_design",
            capability_contract_version=1,
            connector_id=None,
            depends_on=(),
            required_dependencies=(),
            unresolved_inputs=inputs,
            timeout_seconds=spec.timeout_seconds,
            max_attempts=spec.retry.max_attempts,
        ),
    )
    return tuple(sorted(templates, key=lambda item: item.local_id))


def build_design_plan(payload: ProposeModelDesignInput | None = None) -> Plan:
    templates = build_design_templates(payload)
    tasks = tuple(
        PlannedTask(
            local_id=item.local_id,
            capability_id=item.capability_id,
            connector_id=item.connector_id,
            depends_on=item.depends_on,
            inputs=item.unresolved_inputs,
            rationale="LLM designs inside the immutable ArchitectureDecision",
        )
        for item in templates
    )
    return Plan(
        phase=WorkflowState.DESIGN,
        tasks=tasks,
        phase_exit_criteria=DESIGN_EXIT_CRITERIA,
        assumptions=(
            "ArchitectureDecision is chosen by the deterministic rule table",
            (
                "LLM may not change layering, integration, presentation, "
                "history class, or approval_required"
            ),
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
