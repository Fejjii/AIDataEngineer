"""Connector-local re-exports of transformation I/O owned by `aide.capabilities.io`.

DE008A implemented the dbt connector against these documented contracts. MVP002
registers the same schemas in the kernel catalogue so the Governed Tool Gateway
can validate them without importing vendor packages from `aide.capabilities`.
"""

from __future__ import annotations

from typing import Any

from aide.capabilities.io import (
    CompiledModel,
    CompileTransformationInput,
    CompileTransformationOutput,
    ConnectorArtifactRef,
    CreateTransformationInput,
    CreateTransformationOutput,
    ExecuteTransformationInput,
    ExecuteTransformationOutput,
    FrozenModel,
    GetLineageInput,
    GetLineageOutput,
    LineageEdge,
    LineageNode,
    NodeRunResult,
    ParseTransformationInput,
    ParseTransformationOutput,
    RunPipelineInput,
    RunPipelineOutput,
    RunTestsInput,
    RunTestsOutput,
    TestNodeResult,
    TransformationFile,
    TransformationIssue,
    TransformationProjectRef,
    WrittenFile,
)

__all__ = [
    "CompiledModel",
    "CompileTransformationInput",
    "CompileTransformationOutput",
    "ConnectorArtifactRef",
    "CreateTransformationInput",
    "CreateTransformationOutput",
    "ExecuteTransformationInput",
    "ExecuteTransformationOutput",
    "GetLineageInput",
    "GetLineageOutput",
    "InvocationCapture",
    "LineageEdge",
    "LineageNode",
    "NodeRunResult",
    "ParseTransformationInput",
    "ParseTransformationOutput",
    "RunPipelineInput",
    "RunPipelineOutput",
    "RunTestsInput",
    "RunTestsOutput",
    "TestNodeResult",
    "TransformationFile",
    "TransformationIssue",
    "TransformationProjectRef",
    "WrittenFile",
]


class InvocationCapture(FrozenModel):
    selected_nodes: tuple[str, ...]
    invocation_arguments: tuple[str, ...]
    execution_status: str
    artifact_hashes: dict[str, str]
    adapter_response: dict[str, Any] | None = None
