from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import recovery_for, unique_key

from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.dbt.artifacts import parse_manifest, parse_run_results
from aide.connectors.dbt.contracts import (
    CompileTransformationInput,
    CreateTransformationInput,
    ExecuteTransformationInput,
    TransformationFile,
    TransformationProjectRef,
)
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.specs import FAKE_DBT_DEV
from aide.connectors.dbt.workspace import project_dir


@pytest.mark.asyncio
async def test_reconcile_create_transformation_uses_file_hashes(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    context = make_context(operation_idempotency_key=unique_key("create"))
    created = await fake.create_transformation(
        CreateTransformationInput(
            files=(
                TransformationFile(
                    path="models/staging/stg_extra.sql",
                    content="select 1 as id\n",
                ),
            ),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        context,
    )
    locator = {item.path: item.sha256 for item in created.written}
    found = await fake.reconcile(recovery_for(context, "create_transformation", locator=locator))
    assert isinstance(found, EffectFound)
    await fake.close()


@pytest.mark.asyncio
async def test_reconcile_no_effect_when_nothing_ran(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    context = make_context(operation_idempotency_key=unique_key("none"))
    result = await fake.reconcile(recovery_for(context, "execute_transformation"))
    assert isinstance(result, NoEffect)
    await fake.close()


@pytest.mark.asyncio
async def test_reconcile_in_progress(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    context = make_context(operation_idempotency_key=unique_key("run"))
    fake.mark_in_progress(context.operation_idempotency_key)
    result = await fake.reconcile(recovery_for(context, "execute_transformation"))
    assert isinstance(result, InProgress)
    await fake.close()


@pytest.mark.asyncio
async def test_reconcile_unknown_never_infers_success(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    context = make_context(operation_idempotency_key=unique_key("run"))
    created = await fake.create_transformation(
        CreateTransformationInput(
            files=(),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        make_context(workflow_id=context.workflow_id, operation_idempotency_key=unique_key("c")),
    )
    await fake.execute_transformation(
        ExecuteTransformationInput(project_state_id=created.project_state_id),
        context,
    )
    inv = (
        tmp_path
        / ".aide"
        / "work"
        / str(context.workflow_id)
        / "invocations"
        / context.operation_idempotency_key
        / str(context.attempt_id)
        / "target"
        / "run_results.json"
    )
    inv.unlink()
    result = await fake.reconcile(recovery_for(context, "execute_transformation"))
    assert isinstance(result, Unknown)
    await fake.close()


@pytest.mark.asyncio
async def test_manifest_and_run_results_parse(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    create_ctx = make_context(operation_idempotency_key=unique_key("c"))
    created = await fake.create_transformation(
        CreateTransformationInput(
            files=(),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        create_ctx,
    )
    compile_ctx = make_context(
        workflow_id=create_ctx.workflow_id, operation_idempotency_key=unique_key("cmp")
    )
    compiled = await fake.compile_transformation(
        CompileTransformationInput(project_state_id=created.project_state_id),
        compile_ctx,
    )
    assert compiled.ok
    project = project_dir(tmp_path, create_ctx.workflow_id)
    manifest = parse_manifest(project / "target" / "manifest.json")
    assert "nodes" in manifest
    run_ctx = make_context(
        workflow_id=create_ctx.workflow_id, operation_idempotency_key=unique_key("run")
    )
    executed = await fake.execute_transformation(
        ExecuteTransformationInput(project_state_id=created.project_state_id),
        run_ctx,
    )
    assert executed.ok
    run_results = parse_run_results(project / "target" / "run_results.json")
    assert run_results["results"]
    assert compiled.manifest_ref is not None
    assert len(compiled.manifest_ref.sha256) == 64
    capture = (
        tmp_path
        / ".aide"
        / "work"
        / str(create_ctx.workflow_id)
        / "invocations"
        / compile_ctx.operation_idempotency_key
        / str(compile_ctx.attempt_id)
        / "invocation.json"
    )
    assert capture.is_file()
    payload = json.loads(capture.read_text(encoding="utf-8"))
    assert payload["execution_status"] == "COMPLETED"
    assert "manifest.json" in payload["artifact_hashes"]
    await fake.close()
