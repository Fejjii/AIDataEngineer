"""Warehouse protocol adapter over accepted capability handlers."""

from __future__ import annotations

from typing import Any, Protocol

from aide.capabilities.io import (
    DescribeAssetInput,
    DescribeAssetOutput,
    ExecuteQueryInput,
    ExecuteQueryOutput,
    InferRelationshipsInput,
    InferRelationshipsOutput,
    ProfileDatasetInput,
    ProfileDatasetOutput,
    SampleDatasetInput,
    SampleDatasetOutput,
)
from aide.connectors.base.context import CallContext


class WarehouseReadPort(Protocol):
    async def describe_asset(
        self, payload: DescribeAssetInput, context: CallContext
    ) -> DescribeAssetOutput: ...

    async def profile_dataset(
        self, payload: ProfileDatasetInput, context: CallContext
    ) -> ProfileDatasetOutput: ...

    async def sample_dataset(
        self, payload: SampleDatasetInput, context: CallContext
    ) -> SampleDatasetOutput: ...

    async def infer_relationships(
        self, payload: InferRelationshipsInput, context: CallContext
    ) -> InferRelationshipsOutput: ...

    async def execute_query(
        self, payload: ExecuteQueryInput, context: CallContext
    ) -> ExecuteQueryOutput: ...


def upper_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).upper(): value for key, value in row.items()}
