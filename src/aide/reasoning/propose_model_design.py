"""Typed propose_model_design reasoning capability."""

from __future__ import annotations

import json

from aide.capabilities.io import (
    ModelDesign,
    ProposeModelDesignInput,
    canonical_model_layers,
    physical_layer_names,
)
from aide.domain.identity import compute_resolved_input_digest
from aide.llm.gateway import LlmGateway


def propose_model_design(
    payload: ProposeModelDesignInput,
    *,
    gateway: LlmGateway | None = None,
) -> ModelDesign:
    client = gateway or LlmGateway()
    digest = compute_resolved_input_digest(payload.architecture_decision)
    layers = canonical_model_layers(payload.architecture_decision.layering.decision)
    mapping = physical_layer_names(
        payload.architecture_decision.naming,
        payload.architecture_decision.layering.decision,
    )
    result = client.complete(
        "propose_model_design",
        ModelDesign,
        prompt_values={
            "goal": payload.requirement.goal,
            "architecture_decision_json": json.dumps(
                payload.architecture_decision.model_dump(mode="json"),
                sort_keys=True,
            ),
            "assets": [str(item.address) for item in payload.selected_assets],
            "profiling_summary": json.dumps(
                payload.profiling_summary.model_dump(mode="json"), sort_keys=True
            ),
            "profile_evidence": json.dumps(
                [item.model_dump(mode="json") for item in payload.profile_evidence],
                sort_keys=True,
            ),
            "relationship_evidence": json.dumps(
                [item.model_dump(mode="json") for item in payload.relationship_evidence],
                sort_keys=True,
            ),
        },
        extra={
            "architecture_decision_digest": digest,
            "architecture_decision": payload.architecture_decision.model_dump(mode="json"),
        },
    )
    assert isinstance(result, ModelDesign)
    locked = result.model_copy(
        update={
            "architecture_decision_digest": digest,
            "layers": layers or result.layers,
            "physical_layer_names": mapping,
        }
    )
    return locked
