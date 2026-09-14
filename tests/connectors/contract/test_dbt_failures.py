from __future__ import annotations

from pathlib import Path

import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import unique_key

from aide.connectors.dbt.contracts import (
    CompileTransformationInput,
    CreateTransformationInput,
    ExecuteTransformationInput,
    TransformationFile,
    TransformationProjectRef,
)
from aide.connectors.dbt.errors import (
    DbtMappedError,
    DbtProcessTerminatedError,
    DbtTimeoutError,
    map_error,
    map_exception_name,
    map_run_result_status,
)
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.specs import FAKE_DBT_DEV
from aide.domain.failures import FailureClass


def test_compilation_error_maps_to_dbt_compile() -> None:
    exc = type("CompilationError", (Exception,), {})("invalid jinja")
    assert map_error(exc) is FailureClass.DBT_COMPILE
    assert map_exception_name(None, "Compilation Error in model") is FailureClass.DBT_COMPILE
    wrapped = (
        "Runtime Error\n  Compilation Error in model stg_live_compile_fail "
        "(models/staging/stg_live_compile_fail.sql)\n  "
        "'definitely_not_a_macro' is undefined. This can happen when calling "
        "a macro that is not defined or installing package dependencies with "
        '"dbt deps".'
    )
    assert map_exception_name("RuntimeError", wrapped) is FailureClass.DBT_COMPILE


def test_database_error_remaps_through_warehouse_mapper() -> None:
    exc = type("DbtDatabaseError", (Exception,), {})("invalid identifier INVOICE_STATUS")
    assert map_error(exc) is FailureClass.SCHEMA_MISMATCH


def test_unknown_runtime_maps_to_dbt_runtime() -> None:
    exc = type("DbtRuntimeError", (Exception,), {})("something exploded")
    assert map_error(exc) is FailureClass.DBT_RUNTIME


def test_timeout_and_termination_are_explicit() -> None:
    assert map_error(DbtTimeoutError()) is FailureClass.TIMEOUT
    terminated = DbtProcessTerminatedError("killed", signal=9)
    assert map_error(terminated) is FailureClass.CONNECTOR_FAILURE
    assert terminated.reason_code == "PROCESS_TERMINATED"


def test_test_failure_status_maps_to_dbt_test() -> None:
    assert map_run_result_status("fail", None) is FailureClass.DBT_TEST
    assert map_run_result_status("pass", None) is None


@pytest.mark.asyncio
async def test_fake_compile_failure_is_dbt_compile(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    context = make_context(operation_idempotency_key=unique_key("badjinja"))
    created = await fake.create_transformation(
        CreateTransformationInput(
            files=(
                TransformationFile(
                    path="models/staging/stg_bad.sql",
                    content="select {{ run_query('select 1') }} as x\n",
                ),
            ),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        context,
    )
    compiled = await fake.compile_transformation(
        CompileTransformationInput(project_state_id=created.project_state_id),
        make_context(workflow_id=context.workflow_id, operation_idempotency_key=unique_key("c")),
    )
    assert compiled.ok is False
    assert compiled.errors
    assert compiled.errors[0].error_class is FailureClass.DBT_COMPILE
    await fake.close()


@pytest.mark.asyncio
async def test_fail_next_injection(tmp_path: Path) -> None:
    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    fake.fail_next("compile_transformation", FailureClass.DBT_COMPILE)
    created = await fake.create_transformation(
        CreateTransformationInput(
            files=(),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        make_context(operation_idempotency_key=unique_key("c1")),
    )
    with pytest.raises(DbtMappedError) as exc:
        await fake.compile_transformation(
            CompileTransformationInput(project_state_id=created.project_state_id),
            make_context(operation_idempotency_key=unique_key("c2")),
        )
    assert exc.value.failure is FailureClass.DBT_COMPILE
    await fake.close()


@pytest.mark.asyncio
async def test_fail_after_effect_still_reconciles(tmp_path: Path) -> None:
    from tests.connectors.dbt_support import recovery_for

    from aide.connectors.base.reconcile import EffectFound

    fake = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
    create_ctx = make_context(operation_idempotency_key=unique_key("create"))
    created = await fake.create_transformation(
        CreateTransformationInput(
            files=(),
            project_ref=TransformationProjectRef(project_id="vantara"),
        ),
        create_ctx,
    )
    fake.fail_after_effect("execute_transformation")
    run_ctx = make_context(
        workflow_id=create_ctx.workflow_id, operation_idempotency_key=unique_key("run")
    )
    with pytest.raises(DbtMappedError):
        await fake.execute_transformation(
            ExecuteTransformationInput(project_state_id=created.project_state_id),
            run_ctx,
        )
    recovered = await fake.reconcile(recovery_for(run_ctx, "execute_transformation"))
    assert isinstance(recovered, EffectFound)
    await fake.close()
