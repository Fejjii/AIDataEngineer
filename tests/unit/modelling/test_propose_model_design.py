from __future__ import annotations

import json

import pytest
from tests.unit.modelling.factories import (
    vantara_decision,
    vantara_duplicates,
    vantara_profiles,
    vantara_relationships,
)

from aide.capabilities.io import ProfilingEvidenceSummary, ProposeModelDesignInput
from aide.capabilities.v1_kernel import kernel_registry
from aide.domain.identity import compute_resolved_input_digest
from aide.llm.gateway import LlmGateway
from aide.llm.prompts import prompt_root
from aide.modelling.demo_design import vantara_model_design
from aide.modelling.vantara import vantara_demo_requirement
from aide.profiling.fixtures import demo_selected_assets
from aide.reasoning.capabilities import ReasoningCapabilities
from aide.reasoning.propose_model_design import propose_model_design


def test_kernel_registers_propose_model_design() -> None:
    spec = kernel_registry().get("propose_model_design", 1)
    assert spec.kind == "reasoning"
    assert spec.timeout_seconds == 180


def test_recorded_replay_returns_typed_model_design() -> None:
    decision = vantara_decision()
    payload = ProposeModelDesignInput(
        requirement=vantara_demo_requirement(),
        architecture_decision=decision,
        selected_assets=demo_selected_assets(),
        profiling_summary=ProfilingEvidenceSummary(masking_applied=True),
        profile_evidence=vantara_profiles(),
        relationship_evidence=vantara_relationships(),
        duplicate_evidence=vantara_duplicates(),
    )
    design = propose_model_design(payload, gateway=LlmGateway())
    assert design.architecture_decision_digest == compute_resolved_input_digest(decision)
    names = {item.name for item in design.models}
    assert "dim_customer" in names
    assert "fct_invoice_line" in names
    assert design.layers == ("staging", "intermediate", "marts")
    assert design.physical_layer_names == (
        ("staging", "staging"),
        ("intermediate", "intermediate"),
        ("marts", "marts"),
    )


def test_medallion_end_to_end_keeps_canonical_unit_layers() -> None:
    from aide.modelling.context import OrgModellingConfig
    from aide.modelling.validators import validate_model_design
    from aide.modelling.vantara import vantara_modelling_context

    ctx = vantara_modelling_context().model_copy(
        update={"org": OrgModellingConfig(auditability="LOW", naming_convention="MEDALLION")}
    )
    decision = vantara_decision(context=ctx)
    payload = ProposeModelDesignInput(
        requirement=vantara_demo_requirement(),
        architecture_decision=decision,
        selected_assets=demo_selected_assets(),
        profiling_summary=ProfilingEvidenceSummary(masking_applied=True),
        profile_evidence=vantara_profiles(),
        relationship_evidence=vantara_relationships(),
        duplicate_evidence=vantara_duplicates(),
    )
    design = propose_model_design(payload, gateway=LlmGateway())
    assert decision.naming == "MEDALLION"
    assert design.layers == ("staging", "intermediate", "marts")
    assert design.physical_layer_names == (
        ("staging", "bronze"),
        ("intermediate", "silver"),
        ("marts", "gold"),
    )
    assert all(item.layer in {"staging", "intermediate", "marts"} for item in design.models)
    report = validate_model_design(
        design,
        decision,
        selected=demo_selected_assets(),
        profiles=vantara_profiles(),
        duplicates=vantara_duplicates(),
        context=ctx,
    )
    assert report.passed, tuple(item.code for item in report.violations)


def test_reasoner_locks_architecture_decision_digest() -> None:
    decision = vantara_decision()
    payload = ProposeModelDesignInput(
        requirement=vantara_demo_requirement(),
        architecture_decision=decision,
        selected_assets=demo_selected_assets(),
        profiling_summary=ProfilingEvidenceSummary(),
        profile_evidence=vantara_profiles(),
        relationship_evidence=(),
    )
    first = ReasoningCapabilities(LlmGateway()).propose_model_design(payload)
    second = ReasoningCapabilities(LlmGateway()).propose_model_design(payload)
    assert first == second
    assert first.architecture_decision_digest == compute_resolved_input_digest(decision)
    assert all(item.model_kind not in {"HUB", "LINK", "SATELLITE"} for item in first.models)


def test_no_live_provider_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    decision = vantara_decision()
    payload = ProposeModelDesignInput(
        requirement=vantara_demo_requirement(),
        architecture_decision=decision,
        selected_assets=demo_selected_assets(),
        profiling_summary=ProfilingEvidenceSummary(),
        profile_evidence=vantara_profiles(),
        relationship_evidence=(),
    )
    design = propose_model_design(payload)
    assert design.models


def test_recorded_json_matches_demo_design_builder() -> None:
    path = prompt_root() / "propose_model_design" / "recorded_vantara.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    built = vantara_model_design(architecture_decision_digest="0" * 64).model_dump(mode="json")
    fixture["architecture_decision_digest"] = "0" * 64
    assert fixture == built
