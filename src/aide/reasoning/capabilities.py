"""Reasoning capability implementations over the replay gateway."""

from __future__ import annotations

from typing import Any

from aide.capabilities.io import (
    GenerateSqlQueryInput,
    GenerateSqlQueryOutput,
    InterpretRequirementInput,
    Plan,
    PlanPhaseInput,
    RequirementSpec,
    SelectRelevantAssetsInput,
    SelectRelevantAssetsOutput,
)
from aide.domain.sql import AssetRef
from aide.llm.gateway import LlmGateway


class ReasoningCapabilities:
    def __init__(self, gateway: LlmGateway | None = None) -> None:
        self._gateway = gateway or LlmGateway()

    def interpret_requirement(self, payload: InterpretRequirementInput) -> RequirementSpec:
        result = self._gateway.complete(
            "interpret_requirement",
            RequirementSpec,
            prompt_values={"text": payload.text},
            extra={"goal": payload.text},
        )
        assert isinstance(result, RequirementSpec)
        for metric in result.metrics:
            if metric.definition is None:
                raise ValueError("metrics without definition are ambiguous")
        return result

    def plan_phase(
        self,
        payload: PlanPhaseInput,
        *,
        catalogue_assets: tuple[AssetRef, ...] = (),
    ) -> Plan:
        extra: dict[str, Any] = {
            "occurrence": payload.occurrence or "ENUMERATION",
            "catalogue_snapshot_id": payload.catalogue_snapshot_id,
        }
        if catalogue_assets:
            extra["catalogue_assets"] = [item.model_dump(mode="json") for item in catalogue_assets]
        result = self._gateway.complete(
            "plan_phase",
            Plan,
            prompt_values={
                "phase": payload.phase.value,
                "occurrence": extra["occurrence"],
                "contract_snapshot_ref": payload.contract_snapshot_ref,
                "catalogue_snapshot_id": payload.catalogue_snapshot_id,
                "max_tasks": payload.constraints.max_tasks,
            },
            extra=extra,
        )
        assert isinstance(result, Plan)
        return result

    def select_relevant_assets(
        self, payload: SelectRelevantAssetsInput
    ) -> SelectRelevantAssetsOutput:
        result = self._gateway.complete(
            "select_relevant_assets",
            SelectRelevantAssetsOutput,
            prompt_values={
                "goal": payload.requirement.goal,
                "catalogue_snapshot_id": str(payload.catalogue_snapshot_id),
                "assets": [str(item.address) for item in payload.catalogue_assets],
            },
            extra={
                "catalogue_assets": [
                    item.model_dump(mode="json") for item in payload.catalogue_assets
                ]
            },
        )
        assert isinstance(result, SelectRelevantAssetsOutput)
        if len(result.selected) > payload.max_assets:
            raise ValueError("selection exceeds max_assets")
        allowed = {(item.connector_id, item.address) for item in payload.catalogue_assets}
        for item in result.selected:
            if (item.asset.connector_id, item.asset.address) not in allowed:
                raise ValueError("selection is not a subset of the immutable catalogue")
            if not item.reason:
                raise ValueError("selection reason must be non-empty")
        return result

    def generate_sql_query(self, payload: GenerateSqlQueryInput) -> GenerateSqlQueryOutput:
        result = self._gateway.complete(
            "generate_sql_query",
            GenerateSqlQueryOutput,
            prompt_values={
                "dialect": payload.dialect,
                "goal": payload.requirement.goal,
                "assets": [str(item.address) for item in payload.selected_assets],
            },
        )
        assert isinstance(result, GenerateSqlQueryOutput)
        return result
