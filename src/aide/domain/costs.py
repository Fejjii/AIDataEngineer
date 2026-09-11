"""Budget estimate types used by approval and policy R18."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class BudgetScope(str, Enum):
    WORKFLOW_LLM = "WORKFLOW_LLM"
    WORKFLOW_WAREHOUSE = "WORKFLOW_WAREHOUSE"


class CostUnit(str, Enum):
    USD = "USD"
    SNOWFLAKE_CREDITS_ESTIMATED = "SNOWFLAKE_CREDITS_ESTIMATED"


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope: BudgetScope
    unit: CostUnit
    worst_case: Decimal
    current_cap: Decimal
    ledger_version: int = Field(ge=0)
    prior_cap: Decimal | None = None
