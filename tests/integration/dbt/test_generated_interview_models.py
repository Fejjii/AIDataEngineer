from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import unique_key

from aide.capabilities.io import (
    CompileTransformationInput,
    CreateTransformationInput,
    ExecuteTransformationInput,
    GenerateTransformationInput,
    LoadManifestSourcesInput,
    ParseTransformationInput,
    RunTestsInput,
    TransformationProjectRef,
    ValidateInterviewQualityInput,
)
from aide.connectors.base.context import CallContext
from aide.connectors.dbt.config import duckdb_dbt_settings
from aide.connectors.dbt.real import RealDbtConnector
from aide.connectors.dbt.specs import DBT_DEV
from aide.connectors.snowflake.manifest import tiny_manifest_digest
from aide.generation.vantara import generate_vantara_transformation
from aide.modelling.constants import REQUIRED_DEMO_MODELS
from aide.modelling.demo_design import vantara_model_design
from aide.modelling.vantara import vantara_selected_addresses

pytestmark = pytest.mark.dbt_offline


def _ctx(workflow_id: UUID, label: str, deadline_seconds: int = 180) -> CallContext:
    return make_context(
        workflow_id=workflow_id,
        operation_idempotency_key=unique_key(label),
        deadline_seconds=deadline_seconds,
    )


@pytest.mark.asyncio
async def test_generated_interview_models_parse_compile_run_and_test(tmp_path: Path) -> None:
    workflow_id = uuid4()
    generated = generate_vantara_transformation(
        GenerateTransformationInput(workflow_id=workflow_id, model_design=vantara_model_design())
    )
    connector = RealDbtConnector(DBT_DEV, duckdb_dbt_settings(tmp_path))
    connector.ensure_workflow_sources(
        LoadManifestSourcesInput(
            fixture_version="v1",
            manifest_sha256=tiny_manifest_digest(),
            selected_addresses=vantara_selected_addresses(),
        ),
        _ctx(workflow_id, "load"),
    )
    created = await connector.create_transformation(
        CreateTransformationInput(
            files=generated.files,
            project_ref=TransformationProjectRef(project_id="vantara_project"),
            mode="REPLACE",
        ),
        _ctx(workflow_id, "create"),
    )
    parsed = await connector.parse_transformation(
        ParseTransformationInput(project_state_id=created.project_state_id),
        _ctx(workflow_id, "parse"),
    )
    assert parsed.ok, parsed.errors
    compiled = await connector.compile_transformation(
        CompileTransformationInput(project_state_id=created.project_state_id),
        _ctx(workflow_id, "compile"),
    )
    assert compiled.ok, compiled.errors
    executed = await connector.execute_transformation(
        ExecuteTransformationInput(project_state_id=created.project_state_id),
        _ctx(workflow_id, "run", deadline_seconds=300),
    )
    assert executed.ok, tuple((item.model, item.message) for item in executed.results)
    tests = await connector.run_tests(
        RunTestsInput(project_state_id=created.project_state_id),
        _ctx(workflow_id, "test"),
    )
    assert tests.ok, tuple((item.test_name, item.status, item.failures) for item in tests.tests)
    quality = await connector.validate_interview_quality(
        ValidateInterviewQualityInput(
            project_state_id=created.project_state_id,
            required_models=REQUIRED_DEMO_MODELS,
        ),
        _ctx(workflow_id, "quality", deadline_seconds=60),
    )
    assert quality.passed, tuple((item.check_id, item.detail) for item in quality.checks)
    await connector.close()
