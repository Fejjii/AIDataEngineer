from __future__ import annotations

from datetime import UTC, datetime

from tests.unit.modelling.factories import (
    locked_design,
    make_signals,
    vantara_decision,
    vantara_duplicates,
    vantara_profiles,
)

from aide.capabilities.io import DesignValidationReport
from aide.domain.states import LEGAL_TRANSITIONS, WorkflowState
from aide.modelling.service import design_approval_subject, recommended_workflow_state
from aide.modelling.validators import validate_model_design
from aide.modelling.vantara import vantara_modelling_context
from aide.orchestration.phases.design import (
    DESIGN_EXIT_CRITERIA,
    PROPOSE_LOCAL_ID,
    build_design_plan,
    build_design_templates,
)
from aide.profiling.fixtures import demo_selected_assets


def test_design_plan_is_deterministically_ordered() -> None:
    templates = build_design_templates()
    local_ids = [item.local_id for item in templates]
    assert local_ids == sorted(local_ids)
    assert templates[0].local_id == PROPOSE_LOCAL_ID
    plan = build_design_plan()
    assert plan.phase is WorkflowState.DESIGN
    assert plan.phase_exit_criteria == DESIGN_EXIT_CRITERIA
    assert [item.capability_id for item in plan.tasks] == ["propose_model_design"]


def test_valid_design_path_goes_to_planning() -> None:
    decision = vantara_decision()
    report = validate_model_design(
        locked_design(decision),
        decision,
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        duplicates=vantara_duplicates(),
        context=vantara_modelling_context(),
    )
    assert report.passed
    assert recommended_workflow_state(decision, report) is WorkflowState.PLANNING
    assert (WorkflowState.DESIGN, WorkflowState.PLANNING) in LEGAL_TRANSITIONS


def test_approval_flag_path_exposes_design_approval_boundary() -> None:
    decision = vantara_decision(
        signals=make_signals(
            auditability="HIGH",
            source_system_count=4,
            history_requirements="FULL_HISTORY",
            change_frequency="HIGH",
        )
    )
    assert decision.approval_required is True
    report = DesignValidationReport(passed=True, violations=())
    assert recommended_workflow_state(decision, report) is WorkflowState.APPROVAL_REQUIRED
    assert (WorkflowState.DESIGN, WorkflowState.APPROVAL_REQUIRED) in LEGAL_TRANSITIONS
    subject = design_approval_subject(
        locked_design(decision),
        report,
        decision,
        as_of=datetime(2026, 9, 12, tzinfo=UTC),
    )
    assert subject.kind == "DESIGN"
    assert subject.design_artifact_hash
    assert "STAR_SCHEMA" in subject.invariant_hashes


def test_clarification_path_for_blocking_questions() -> None:
    decision = vantara_decision(signals=make_signals(history_requirements="UNKNOWN"))
    report = DesignValidationReport(passed=True, violations=())
    assert recommended_workflow_state(decision, report) is WorkflowState.CLARIFICATION_REQUIRED
    assert (WorkflowState.DESIGN, WorkflowState.CLARIFICATION_REQUIRED) in LEGAL_TRANSITIONS


def test_serialization_of_design_plan() -> None:
    plan = build_design_plan()
    restored = plan.__class__.model_validate(plan.model_dump(mode="json"))
    assert restored == plan
    assert restored.tasks[0].local_id == PROPOSE_LOCAL_ID


def test_failed_validation_path_is_blocked() -> None:
    decision = vantara_decision()
    design = locked_design(decision).model_copy(
        update={
            "models": tuple(
                item for item in locked_design(decision).models if item.name != "dim_customer"
            )
        }
    )
    report = validate_model_design(
        design,
        decision,
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        duplicates=vantara_duplicates(),
        context=vantara_modelling_context(),
    )
    assert not report.passed
    assert recommended_workflow_state(decision, report) is WorkflowState.BLOCKED
    assert (WorkflowState.DESIGN, WorkflowState.BLOCKED) in LEGAL_TRANSITIONS
