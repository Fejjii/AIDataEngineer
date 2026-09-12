"""DESIGN phase runner: decide, propose, validate, expose DesignApproval boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from aide.capabilities.io import (
    ArchitectureDecision,
    DesignValidationReport,
    ModelDesign,
    ProposeModelDesignInput,
    RequirementSpec,
)
from aide.domain.approvals import DesignApproval
from aide.domain.identity import compute_resolved_input_digest
from aide.domain.sql import AssetRef
from aide.domain.states import WorkflowState
from aide.llm.gateway import LlmGateway
from aide.modelling.context import ModellingContext
from aide.modelling.engine import decide_architecture
from aide.modelling.evidence import evidence_from_run
from aide.modelling.validators import validate_model_design
from aide.profiling.artifacts import ProfilingRunResult
from aide.reasoning.propose_model_design import propose_model_design


class DesignPhaseResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    architecture_decision: ArchitectureDecision
    model_design: ModelDesign | None
    validation: DesignValidationReport
    recommended_next_state: WorkflowState
    approval_required: bool
    design_approval: DesignApproval | None = None


def build_propose_input(
    requirement: RequirementSpec,
    decision: ArchitectureDecision,
    run: ProfilingRunResult,
    selected: tuple[AssetRef, ...],
) -> ProposeModelDesignInput:
    profiles, relationships, duplicates, summary = evidence_from_run(run)
    return ProposeModelDesignInput(
        requirement=requirement,
        architecture_decision=decision,
        selected_assets=selected,
        profiling_summary=summary,
        profile_evidence=profiles,
        relationship_evidence=relationships,
        duplicate_evidence=duplicates,
    )


def recommended_workflow_state(
    decision: ArchitectureDecision, validation: DesignValidationReport
) -> WorkflowState:
    if any(item.blocking for item in decision.open_questions):
        return WorkflowState.CLARIFICATION_REQUIRED
    if not validation.passed:
        return WorkflowState.BLOCKED
    if decision.approval_required:
        return WorkflowState.APPROVAL_REQUIRED
    return WorkflowState.PLANNING


def design_approval_subject(
    design: ModelDesign,
    validation: DesignValidationReport,
    decision: ArchitectureDecision,
    *,
    as_of: datetime,
    ttl: timedelta = timedelta(days=7),
) -> DesignApproval:
    return DesignApproval(
        design_artifact_hash=compute_resolved_input_digest(design),
        validation_report_hash=compute_resolved_input_digest(validation),
        invariant_hashes=(
            compute_resolved_input_digest(decision),
            decision.layering.decision,
            decision.integration_layer.decision,
            decision.presentation.decision,
            "approval_required=" + ("true" if decision.approval_required else "false"),
        ),
        expires_at=as_of + ttl,
    )


def run_design_phase(
    requirement: RequirementSpec,
    run: ProfilingRunResult,
    selected: tuple[AssetRef, ...],
    *,
    context: ModellingContext | None = None,
    gateway: LlmGateway | None = None,
    as_of: datetime | None = None,
) -> DesignPhaseResult:
    decision = decide_architecture(requirement, selected=selected, run=run, context=context)
    payload = build_propose_input(requirement, decision, run, selected)
    design = propose_model_design(payload, gateway=gateway)
    profiles, _relationships, duplicates, _summary = evidence_from_run(run)
    validation = validate_model_design(
        design,
        decision,
        selected=selected,
        profiles=profiles,
        duplicates=duplicates,
        context=context,
    )
    next_state = recommended_workflow_state(decision, validation)
    approval = None
    now = as_of or datetime.now(UTC)
    if decision.approval_required:
        approval = design_approval_subject(design, validation, decision, as_of=now)
    return DesignPhaseResult(
        architecture_decision=decision,
        model_design=design,
        validation=validation,
        recommended_next_state=next_state,
        approval_required=decision.approval_required,
        design_approval=approval,
    )
