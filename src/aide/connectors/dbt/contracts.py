"""Connector-local transformation I/O matching docs/TOOL_CONTRACTS.md.

Kernel capability registration lives in `aide.capabilities` and is owned by
other tasks. DE008A implements the connector against these documented contracts
without modifying the capability registry. Canonical Tool Registry wiring is a
DE008B integration step and is not yet product-integrated.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from aide.capabilities.io import FrozenModel
from aide.domain.artifacts import ArtifactProvenance
from aide.domain.failures import FailureClass


class TransformationFile(FrozenModel):
    path: str = Field(min_length=1)
    content: str
    kind: Literal["MODEL_SQL", "SCHEMA_YML", "SOURCE_YML", "MACRO", "SNAPSHOT", "DOC_MD"] = (
        "MODEL_SQL"
    )


class TransformationProjectRef(FrozenModel):
    project_id: str = Field(min_length=1)
    root: str | None = None
    platform: Literal["dbt"] = "dbt"


class ConnectorArtifactRef(FrozenModel):
    artifact_id: UUID
    sha256: str = Field(min_length=64, max_length=64)
    type: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    schema_version: int = Field(default=1, ge=1)
    provenance: ArtifactProvenance | None = None


class WrittenFile(FrozenModel):
    path: str
    sha256: str = Field(min_length=64, max_length=64)


class CreateTransformationInput(FrozenModel):
    artifact_set: tuple[ConnectorArtifactRef, ...] = ()
    files: tuple[TransformationFile, ...]
    project_ref: TransformationProjectRef
    mode: Literal["ADD", "REPLACE"] = "ADD"


class CreateTransformationOutput(FrozenModel):
    written: tuple[WrittenFile, ...]
    project_state_id: UUID


class CompileTransformationInput(FrozenModel):
    project_state_id: UUID
    select: tuple[str, ...] | None = None
    target: Literal["DEV"] = "DEV"


class CompiledModel(FrozenModel):
    model: str
    compiled_sql_ref: ConnectorArtifactRef | None = None
    compiled_sql: str | None = None


class TransformationIssue(FrozenModel):
    model: str | None = None
    message: str
    error_class: FailureClass


class CompileTransformationOutput(FrozenModel):
    ok: bool
    manifest_ref: ConnectorArtifactRef | None = None
    compiled: tuple[CompiledModel, ...] = ()
    errors: tuple[TransformationIssue, ...] = ()


class ExecuteTransformationInput(FrozenModel):
    project_state_id: UUID
    select: tuple[str, ...] = ()
    full_refresh: bool = False
    target: Literal["DEV"] = "DEV"


class NodeRunResult(FrozenModel):
    model: str
    status: Literal["success", "error", "skipped"]
    execution_time_s: float = 0.0
    rows_affected: int | None = None
    message: str | None = None
    error_class: FailureClass | None = None


class ExecuteTransformationOutput(FrozenModel):
    ok: bool
    results: tuple[NodeRunResult, ...]
    run_results_ref: ConnectorArtifactRef | None = None


class TestNodeResult(FrozenModel):
    test_name: str
    model: str | None = None
    column: str | None = None
    status: Literal["pass", "fail", "warn", "error"]
    failures: int | None = None


class RunPipelineInput(FrozenModel):
    project_state_id: UUID
    select: tuple[str, ...] | None = None
    full_refresh: bool = False
    target: Literal["DEV"] = "DEV"


class RunPipelineOutput(FrozenModel):
    ok: bool
    results: tuple[NodeRunResult, ...]
    tests: tuple[TestNodeResult, ...] = ()
    run_results_ref: ConnectorArtifactRef | None = None


class RunTestsInput(FrozenModel):
    project_state_id: UUID
    select: tuple[str, ...] | None = None
    store_failures: bool = False


class RunTestsOutput(FrozenModel):
    ok: bool
    tests: tuple[TestNodeResult, ...]
    run_results_ref: ConnectorArtifactRef | None = None


class GetLineageInput(FrozenModel):
    manifest_ref: ConnectorArtifactRef | None = None
    project_state_id: UUID | None = None
    column_level: bool = False


class LineageNode(FrozenModel):
    id: str
    kind: Literal["source", "model", "seed", "snapshot", "test"]
    name: str


class LineageEdge(FrozenModel):
    from_id: str
    to_id: str
    columns: tuple[tuple[str, str], ...] | None = None


class GetLineageOutput(FrozenModel):
    nodes: tuple[LineageNode, ...]
    edges: tuple[LineageEdge, ...]
    lineage_ref: ConnectorArtifactRef | None = None


class InvocationCapture(FrozenModel):
    selected_nodes: tuple[str, ...]
    invocation_arguments: tuple[str, ...]
    execution_status: str
    artifact_hashes: dict[str, str]
    adapter_response: dict[str, Any] | None = None
