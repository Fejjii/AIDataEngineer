from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import unique_key

from aide.connectors.base.registry import startup_permission_check
from aide.connectors.dbt.contracts import (
    CompileTransformationInput,
    CreateTransformationInput,
    ExecuteTransformationInput,
    GetLineageInput,
    RunPipelineInput,
    RunTestsInput,
    TransformationFile,
    TransformationProjectRef,
)
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.specs import DBT_DEV, DBT_REQUIRED_PERMISSIONS, FAKE_DBT_DEV
from aide.domain.permissions import PermissionLevel


@pytest.fixture
def fake_dbt(tmp_path: Path) -> FakeDbtConnector:
    return FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)


def test_dbt_advertisements_and_permissions() -> None:
    startup_permission_check(DBT_DEV, DBT_REQUIRED_PERMISSIONS)
    startup_permission_check(FAKE_DBT_DEV, DBT_REQUIRED_PERMISSIONS)
    for capability_id in DBT_REQUIRED_PERMISSIONS:
        assert DBT_DEV.advertises(capability_id, 1)
        assert FAKE_DBT_DEV.advertises(capability_id, 1)
    assert PermissionLevel.READ in DBT_DEV.allowed_permissions
    assert PermissionLevel.DEVELOPMENT_EXECUTE in DBT_DEV.allowed_permissions
    assert PermissionLevel.DEVELOPMENT_WRITE in DBT_DEV.allowed_permissions
    assert DBT_DEV.identity_class.value == "DEVELOPMENT"
    assert DBT_DEV.kind.value == "transformation"


def test_dbt_core_and_duckdb_are_importable() -> None:
    from importlib.metadata import version

    assert version("dbt-core").startswith("1.11.")
    assert version("dbt-duckdb").startswith("1.11.")
    assert importlib.util.find_spec("dbt") is not None
    assert importlib.util.find_spec("dbt.adapters.duckdb") is not None


def test_fake_and_real_handler_parity() -> None:
    from aide.connectors.dbt.config import duckdb_dbt_settings
    from aide.connectors.dbt.real import RealDbtConnector

    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=Path("/tmp"))
    real = RealDbtConnector(DBT_DEV, duckdb_dbt_settings(Path("/tmp")))
    for name in (
        "create_transformation",
        "compile_transformation",
        "execute_transformation",
        "run_pipeline",
        "run_tests",
        "get_lineage",
        "reconcile",
        "health",
        "close",
    ):
        assert callable(getattr(fake, name))
        assert callable(getattr(real, name))


@pytest.mark.asyncio
async def test_fake_health_is_mock(fake_dbt: FakeDbtConnector) -> None:
    snapshot = await fake_dbt.health()
    assert snapshot.status == "MOCK"
    await fake_dbt.close()


@pytest.mark.asyncio
async def test_real_duckdb_health_is_available(tmp_path: Path) -> None:
    from aide.connectors.dbt.config import duckdb_dbt_settings
    from aide.connectors.dbt.real import RealDbtConnector

    connector = RealDbtConnector(DBT_DEV, duckdb_dbt_settings(tmp_path))
    snapshot = await connector.health()
    assert snapshot.status == "AVAILABLE"
    assert snapshot.reason_codes == ()
    await connector.close()


@pytest.mark.asyncio
async def test_fake_compile_execute_and_tests(fake_dbt: FakeDbtConnector) -> None:
    context = make_context(operation_idempotency_key=unique_key("create"))
    created = await fake_dbt.create_transformation(
        CreateTransformationInput(
            files=(
                TransformationFile(
                    path="models/staging/stg_generated.sql",
                    content=(
                        "{{ config(materialized='view') }}\n"
                        "select customer_id from {{ source('vantara_raw', 'customers') }}\n"
                    ),
                ),
            ),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        context,
    )
    assert created.written
    compile_ctx = make_context(
        workflow_id=context.workflow_id, operation_idempotency_key=unique_key("compile")
    )
    compiled = await fake_dbt.compile_transformation(
        CompileTransformationInput(project_state_id=created.project_state_id),
        compile_ctx,
    )
    assert compiled.ok
    assert compiled.manifest_ref is not None
    assert any(item.model == "stg_billing__invoices" for item in compiled.compiled)
    assert any("VANTARA_RAW" in (item.compiled_sql or "") for item in compiled.compiled)
    run_ctx = make_context(
        workflow_id=context.workflow_id, operation_idempotency_key=unique_key("run")
    )
    executed = await fake_dbt.execute_transformation(
        ExecuteTransformationInput(project_state_id=created.project_state_id),
        run_ctx,
    )
    assert executed.ok
    assert executed.run_results_ref is not None
    from aide.connectors.dbt.journal import DispatchStatus, latest_journal
    from aide.connectors.dbt.workspace import invocation_dir
    from aide.domain.effects import EffectSemantics

    journal = latest_journal(
        invocation_dir(
            fake_dbt.work_root,
            run_ctx.workflow_id,
            run_ctx.operation_idempotency_key,
            run_ctx.attempt_id,
        )
    )
    assert journal is not None
    assert journal.effect_semantics is EffectSemantics.NON_IDEMPOTENT
    assert journal.dispatch_status is DispatchStatus.COMPLETED
    assert journal.artifact_hashes
    test_ctx = make_context(
        workflow_id=context.workflow_id, operation_idempotency_key=unique_key("test")
    )
    tests = await fake_dbt.run_tests(
        RunTestsInput(project_state_id=created.project_state_id),
        test_ctx,
    )
    assert tests.ok
    assert tests.tests
    lineage_ctx = make_context(
        workflow_id=context.workflow_id,
        operation_idempotency_key=compile_ctx.operation_idempotency_key,
    )
    lineage = await fake_dbt.get_lineage(
        GetLineageInput(project_state_id=created.project_state_id),
        lineage_ctx,
    )
    assert any(node.kind == "model" for node in lineage.nodes)
    await fake_dbt.close()


@pytest.mark.asyncio
async def test_fake_run_pipeline(fake_dbt: FakeDbtConnector) -> None:
    context = make_context(operation_idempotency_key=unique_key("pipe"))
    created = await fake_dbt.create_transformation(
        CreateTransformationInput(
            files=(),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        context,
    )
    built = await fake_dbt.run_pipeline(
        RunPipelineInput(project_state_id=created.project_state_id),
        make_context(
            workflow_id=context.workflow_id, operation_idempotency_key=unique_key("build")
        ),
    )
    assert built.ok
    assert built.results
    await fake_dbt.close()


@pytest.mark.asyncio
async def test_create_transformation_rejects_path_escape(fake_dbt: FakeDbtConnector) -> None:
    from aide.connectors.dbt.errors import DbtMappedError
    from aide.domain.failures import FailureClass

    context = make_context(operation_idempotency_key=unique_key("escape"))
    with pytest.raises(DbtMappedError) as exc:
        await fake_dbt.create_transformation(
            CreateTransformationInput(
                files=(TransformationFile(path="../outside.sql", content="select 1\n"),),
                project_ref=TransformationProjectRef(project_id="vantara"),
            ),
            context,
        )
    assert exc.value.failure is FailureClass.UNSAFE_OPERATION
    await fake_dbt.close()


@pytest.mark.asyncio
async def test_create_transformation_rejects_dbt_project(fake_dbt: FakeDbtConnector) -> None:
    from aide.connectors.dbt.errors import DbtMappedError
    from aide.domain.failures import FailureClass

    context = make_context(operation_idempotency_key=unique_key("proj"))
    with pytest.raises(DbtMappedError) as exc:
        await fake_dbt.create_transformation(
            CreateTransformationInput(
                files=(TransformationFile(path="dbt_project.yml", content="name: hack\n"),),
                project_ref=TransformationProjectRef(project_id="vantara"),
            ),
            context,
        )
    assert exc.value.failure is FailureClass.UNSAFE_OPERATION
    await fake_dbt.close()
