from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from aide.app.groups import (
    classify_reliability_noop,
    interpret_customer_revenue_request,
    plan_interview_phase,
    propose_relevant_assets,
)
from aide.capabilities.io import (
    CatalogAsset,
    DiscoverAssetsOutput,
    PlanConstraints,
    PlanPhaseInput,
)
from aide.domain.sql import AssetKind
from aide.domain.states import WorkflowState
from aide.modelling.vantara import vantara_demo_requirement, vantara_selected_addresses

GROUPS_PATH = Path("src/aide/app/groups.py")
FORBIDDEN_NAMES = frozenset(
    {
        "GovernedToolGateway",
        "AsyncSession",
        "sessionmaker",
        "FakeSnowflakeConnector",
        "FakeDbtConnector",
        "RealSnowflakeConnector",
        "RealDbtConnector",
        "ConnectorRegistry",
        "ToolRegistry",
    }
)


def test_groups_source_has_no_connector_or_session_handles() -> None:
    tree = ast.parse(GROUPS_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
            if node.module:
                imported.add(node.module.split(".")[-1])
    assert imported.isdisjoint(FORBIDDEN_NAMES)
    source = GROUPS_PATH.read_text(encoding="utf-8")
    assert "GovernedToolGateway" not in source
    assert "AsyncSession" not in source


def test_interpret_customer_revenue_is_locked_vantara_requirement() -> None:
    interpreted = interpret_customer_revenue_request("any operator wording")
    assert interpreted == vantara_demo_requirement()


def test_plan_interview_phase_does_not_emit_tasks() -> None:
    plan = plan_interview_phase(
        PlanPhaseInput(
            workflow_context_ref="wf",
            phase=WorkflowState.DISCOVERY,
            contract_snapshot_ref="snap",
            capability_catalogue=(),
            constraints=PlanConstraints(max_tasks=10, effective_grants=("READ",)),
            occurrence="ENUMERATION",
        )
    )
    assert plan.tasks == ()
    assert plan.phase is WorkflowState.DISCOVERY


def test_propose_relevant_assets_intersects_locked_set() -> None:
    wanted = vantara_selected_addresses()
    extra = CatalogAsset(
        connector_id="snowflake_ro",
        address=("VANTARA_RAW", "SUPPORT", "TICKETS"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    locked = tuple(
        CatalogAsset(
            connector_id="snowflake_ro",
            address=address,
            kind=AssetKind.TABLE,
            platform_type="snowflake",
        )
        for address in wanted
    )
    selected = propose_relevant_assets(
        DiscoverAssetsOutput(assets=(*locked, extra), snapshot_id=uuid4())
    )
    selected_addresses = {item.asset.address for item in selected.selected}
    assert selected_addresses == set(wanted)
    assert any(item.asset.address == extra.address for item in selected.excluded_notable)


def test_reliability_group_is_a_noop() -> None:
    assert classify_reliability_noop() is False
