"""Interview MVP capability groups.

These are typed, tool-less functions. They are not principals, processes, agents,
or tool authorities. They cannot mutate workflow state or receive connector,
session, or gateway handles.
"""

from __future__ import annotations

from aide.capabilities.io import (
    DiscoverAssetsOutput,
    ExcludedAsset,
    Plan,
    PlanPhaseInput,
    RequirementSpec,
    SelectedAsset,
    SelectRelevantAssetsOutput,
)
from aide.domain.sql import AssetRef
from aide.modelling.vantara import vantara_demo_requirement, vantara_selected_addresses


def interpret_customer_revenue_request(text: str) -> RequirementSpec:
    """Return the locked Vantara customer-revenue requirement for the Interview MVP."""
    del text
    return vantara_demo_requirement()


def plan_interview_phase(payload: PlanPhaseInput) -> Plan:
    """Materialize a recorded plan boundary. Supervisor owns the next templates."""
    return Plan(
        phase=payload.phase,
        tasks=(),
        phase_exit_criteria=("planning_boundary",),
        assumptions=("fixed Interview MVP workflow",),
    )


def propose_relevant_assets(
    discovered: DiscoverAssetsOutput,
    *,
    selected_addresses: tuple[tuple[str, str, str], ...] | None = None,
) -> SelectRelevantAssetsOutput:
    """Intersect discovery with the locked ten-table customer-revenue set."""
    wanted = selected_addresses or vantara_selected_addresses()
    wanted_set = {tuple(item) for item in wanted}
    selected: list[SelectedAsset] = []
    excluded: list[AssetRef] = []
    for asset in discovered.assets:
        if asset.address in wanted_set:
            selected.append(
                SelectedAsset(
                    asset=AssetRef(
                        connector_id=asset.connector_id,
                        address=asset.address,
                        kind=asset.kind,
                        platform_type=asset.platform_type,
                    ),
                    role="SOURCE",
                    reason="locked Interview MVP customer-revenue table",
                    confidence=1.0,
                )
            )
        else:
            excluded.append(
                AssetRef(
                    connector_id=asset.connector_id,
                    address=asset.address,
                    kind=asset.kind,
                    platform_type=asset.platform_type,
                )
            )
    return SelectRelevantAssetsOutput(
        selected=tuple(selected),
        excluded_notable=tuple(
            ExcludedAsset(asset=item, reason="outside locked Interview MVP table set")
            for item in excluded
        ),
    )


def classify_reliability_noop() -> None:
    """Reliability is a documented group; MVP002 does not apply repairs."""
    return None
