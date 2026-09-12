"""Deterministic recorded LLM responses. No live provider credentials."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from aide.llm.prompts import render_prompt

PROMPT_VERSION = 1


class ReplayError(ValueError):
    pass


def replay_structured(
    capability_id: str,
    schema: type[BaseModel],
    *,
    prompt_values: Mapping[str, object],
    extra: Mapping[str, Any] | None = None,
) -> BaseModel:
    """Render a versioned prompt, then validate a recorded structured payload."""
    prompt = render_prompt(capability_id, PROMPT_VERSION, **prompt_values)
    if "interpret_requirement@v1" not in prompt and capability_id == "interpret_requirement":
        raise ReplayError("prompt artifact was not rendered")
    payload = recorded_payload(capability_id, extra or {})
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise ReplayError(f"recorded output failed {schema.__name__}: {exc}") from exc


def recorded_payload(capability_id: str, extra: Mapping[str, Any]) -> dict[str, Any]:
    if capability_id == "interpret_requirement":
        return {
            "goal": str(extra.get("goal", "Investigate recent order amounts by customer")),
            "deliverable_type": "INVESTIGATION",
            "business_entities": [
                {"name": "order", "description": "sales order header"},
                {"name": "customer", "description": "selling customer"},
            ],
            "metrics": [
                {
                    "name": "order_amount",
                    "definition": "SUM(AMOUNT)",
                    "ambiguous": False,
                }
            ],
            "grain_hints": ["ORDER_ID"],
            "history_requirements": "CURRENT_ONLY",
            "freshness_requirement": "daily",
            "consumers": ["analytics-engineer"],
            "constraints": ["read-only", "DEV only"],
            "ambiguities": [
                {
                    "topic": "time_window",
                    "question": "Is a specific date range required?",
                    "options": ["all history", "last 30 days"],
                    "blocking": False,
                }
            ],
            "out_of_scope": ["production deploy", "dbt models"],
        }
    if capability_id == "plan_phase":
        occurrence = str(extra.get("occurrence", "ENUMERATION"))
        return _plan_payload(occurrence, extra)
    if capability_id == "select_relevant_assets":
        assets = extra.get("catalogue_assets", ())
        selected: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for index, asset in enumerate(assets):
            dumped = _asset_dump(asset)
            if dumped["address"][-1] == "ACCOUNTS":
                excluded.append(
                    {
                        "asset": dumped,
                        "reason": "CRM accounts are a lookup, not the measure grain",
                    }
                )
            else:
                selected.append(
                    {
                        "asset": dumped,
                        "role": "SOURCE" if index == 0 else "REFERENCE",
                        "reason": "Required to compute order amounts",
                        "confidence": 0.9,
                    }
                )
        return {"selected": selected, "excluded_notable": excluded}
    if capability_id == "generate_sql_query":
        sql = (
            "SELECT c.CUSTOMER_ID, c.CUSTOMER_NAME, SUM(o.AMOUNT) AS ORDER_AMOUNT "
            "FROM RAW.SALES.ORDERS o "
            "JOIN RAW.SALES.CUSTOMERS c ON o.CUSTOMER_ID = c.CUSTOMER_ID "
            "GROUP BY c.CUSTOMER_ID, c.CUSTOMER_NAME"
        )
        return {
            "sql": {"dialect": "snowflake", "text": sql},
            "explanation": (
                "Aggregate order amount by customer from the immutable catalogue subset."
            ),
            "expected_columns": [
                {"name": "CUSTOMER_ID", "type_hint": "NUMBER"},
                {"name": "CUSTOMER_NAME", "type_hint": "VARCHAR"},
                {"name": "ORDER_AMOUNT", "type_hint": "NUMBER"},
            ],
            "expected_grain": ["CUSTOMER_ID"],
            "assumptions": ["AMOUNT is the order value"],
        }
    raise ReplayError(f"no recorded response for {capability_id}")


def _asset_dump(asset: object) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise ReplayError("catalogue assets must be dumped dictionaries")
    return {
        "connector_id": asset["connector_id"],
        "address": list(asset["address"]),
        "kind": asset.get("kind", "TABLE"),
        "platform_type": asset.get("platform_type"),
    }


def _plan_payload(occurrence: str, extra: Mapping[str, Any]) -> dict[str, Any]:
    if occurrence == "ENUMERATION":
        return {
            "phase": "DISCOVERY",
            "tasks": [
                {
                    "local_id": "d1",
                    "capability_id": "discover_assets",
                    "connector_id": "snowflake_ro",
                    "depends_on": [],
                    "inputs": {
                        "scope": {"databases": ["RAW", "AIDE_DEV"], "include_views": False},
                        "filters": {},
                    },
                    "rationale": "Enumerate allow-listed warehouse assets.",
                }
            ],
            "phase_exit_criteria": ["immutable_sorted_metadata_catalog"],
            "assumptions": ["catalogue-only exit"],
        }
    if occurrence == "DESCRIPTION":
        assets = tuple(extra.get("catalogue_assets", ()))
        dumped_assets = tuple(_asset_dump(item) for item in assets)
        sorted_assets = tuple(sorted(dumped_assets, key=lambda item: tuple(item["address"])))
        describe_tasks: list[dict[str, Any]] = []
        for index, asset in enumerate(sorted_assets, start=1):
            local_id = f"d2.{index:02d}"
            describe_tasks.append(
                {
                    "local_id": local_id,
                    "capability_id": "describe_asset",
                    "connector_id": "snowflake_ro",
                    "depends_on": [],
                    "inputs": {
                        "asset": asset,
                        "include_constraints": True,
                        "include_row_count": True,
                    },
                    "rationale": "Describe one catalogue candidate.",
                }
            )
        select_depends = [task["local_id"] for task in describe_tasks]
        describe_tasks.append(
            {
                "local_id": "d3",
                "capability_id": "select_relevant_assets",
                "connector_id": None,
                "depends_on": select_depends,
                "inputs": {
                    "catalogue_snapshot_id": str(extra.get("catalogue_snapshot_id")),
                    "max_assets": 8,
                },
                "rationale": "Select a subset of the immutable catalogue.",
            }
        )
        return {
            "phase": "DISCOVERY",
            "tasks": describe_tasks,
            "phase_exit_criteria": [
                "immutable_sorted_metadata_catalog",
                "asset_selection",
            ],
            "assumptions": ["explicit sorted fan-out after planning boundary"],
        }
    return {
        "phase": "GENERATION",
        "tasks": [
            {
                "local_id": "g1",
                "capability_id": "generate_sql_query",
                "connector_id": None,
                "depends_on": [],
                "inputs": {},
                "rationale": "Generate one read-only investigation query.",
            },
            {
                "local_id": "g2",
                "capability_id": "classify_sql",
                "connector_id": None,
                "depends_on": ["g1"],
                "inputs": {},
                "rationale": "Classify generated SQL.",
            },
            {
                "local_id": "g3",
                "capability_id": "validate_query",
                "connector_id": "snowflake_ro",
                "depends_on": ["g2"],
                "inputs": {"mode": "EXPLAIN"},
                "rationale": "EXPLAIN the classified statement.",
            },
            {
                "local_id": "e1",
                "capability_id": "execute_query",
                "connector_id": "snowflake_ro",
                "depends_on": ["g3"],
                "inputs": {
                    "budget": {"max_rows": 100, "max_bytes": 65536, "max_seconds": 30},
                    "result_mode": "ROWS",
                },
                "rationale": "Execute the validated read-only statement.",
            },
        ],
        "phase_exit_criteria": ["validated_query_result"],
        "assumptions": ["READ binds snowflake_ro"],
    }
