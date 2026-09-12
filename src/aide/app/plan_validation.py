"""Structural plan validation. Temporary connector health is excluded."""

from __future__ import annotations

from aide.capabilities.io import Plan, PlannedTask
from aide.capabilities.registry import CapabilityRegistry
from aide.connectors.base.registry import ConnectorRegistry
from aide.connectors.base.spec import IdentityClass
from aide.orchestration.materialization import TemplateSpec


class PlanValidationError(ValueError):
    pass


def validate_plan(
    plan: Plan,
    *,
    capabilities: CapabilityRegistry,
    connectors: ConnectorRegistry,
    max_tasks: int = 50,
) -> tuple[TemplateSpec, ...]:
    if len(plan.tasks) > max_tasks:
        raise PlanValidationError("plan exceeds max_tasks")
    local_ids = [task.local_id for task in plan.tasks]
    if len(local_ids) != len(set(local_ids)):
        raise PlanValidationError("task local_ids must be unique")
    known = set(local_ids)
    for task in plan.tasks:
        if not set(task.depends_on).issubset(known):
            raise PlanValidationError("cross-phase or unknown dependency is forbidden")
        spec = capabilities.get(task.capability_id, 1)
        if spec.connector_requirement.required:
            if task.connector_id is None:
                raise PlanValidationError(f"{task.capability_id} requires a connector")
            connector = connectors.get(task.connector_id)
            if not connector.advertises(task.capability_id, spec.version):
                raise PlanValidationError(
                    f"{task.connector_id} does not advertise {task.capability_id}"
                )
            if (
                spec.required_permission.value == "READ"
                and connector.kind.value in {"warehouse", "database"}
                and connector.identity_class is not IdentityClass.READ_ONLY
            ):
                raise PlanValidationError("warehouse READ must bind READ_ONLY identity")
        elif task.connector_id is not None:
            raise PlanValidationError(f"{task.capability_id} must not bind a connector")
    if _cyclic(plan.tasks):
        raise PlanValidationError("plan DAG is cyclic")
    templates = [
        TemplateSpec(
            local_id=task.local_id,
            capability_id=task.capability_id,
            capability_contract_version=1,
            connector_id=task.connector_id,
            depends_on=tuple(sorted(task.depends_on)),
            required_dependencies=tuple(sorted(task.depends_on)),
            unresolved_inputs=task.inputs,
            timeout_seconds=capabilities.get(task.capability_id, 1).timeout_seconds,
            max_attempts=capabilities.get(task.capability_id, 1).retry.max_attempts,
        )
        for task in plan.tasks
    ]
    return tuple(sorted(templates, key=lambda item: item.local_id))


def _cyclic(tasks: tuple[PlannedTask, ...]) -> bool:
    remaining = {task.local_id: set(task.depends_on) for task in tasks}
    ready = [local_id for local_id, deps in remaining.items() if not deps]
    seen = 0
    while ready:
        current = ready.pop()
        seen += 1
        for local_id, deps in remaining.items():
            if current in deps:
                deps.remove(current)
                if not deps:
                    ready.append(local_id)
    return seen != len(tasks)
