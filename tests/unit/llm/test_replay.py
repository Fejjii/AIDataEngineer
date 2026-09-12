from __future__ import annotations

from aide.capabilities.io import InterpretRequirementInput, RequirementSpec
from aide.llm.gateway import LlmGateway
from aide.reasoning.capabilities import ReasoningCapabilities


def test_offline_replay_is_deterministic() -> None:
    reasoner = ReasoningCapabilities(LlmGateway())
    first = reasoner.interpret_requirement(
        InterpretRequirementInput(text="Investigate order amounts")
    )
    second = reasoner.interpret_requirement(
        InterpretRequirementInput(text="Investigate order amounts")
    )
    assert first == second
    assert isinstance(first, RequirementSpec)
    assert first.deliverable_type == "INVESTIGATION"
