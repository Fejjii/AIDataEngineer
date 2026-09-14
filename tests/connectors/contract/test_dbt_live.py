"""Live Snowflake dbt validation. Skipped when DEV credentials are absent."""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from synthetic.vantara.export.snowflake_export import (
    COPY_FILE_FORMAT,
    columns_for_v2,
    csv_relative_path,
    snowflake_type,
)
from synthetic.vantara.schema import TABLES
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import recovery_for, unique_key

from aide.capabilities.io import Budget, ExecuteQueryInput, ExecuteQueryOutput
from aide.connectors.base.context import CallContext
from aide.connectors.base.reconcile import EffectFound
from aide.connectors.base.v1_instances import SNOWFLAKE_DEV, SNOWFLAKE_RO
from aide.connectors.dbt.artifacts import parse_manifest, parse_run_results
from aide.connectors.dbt.config import snowflake_dbt_credentials_available
from aide.connectors.dbt.contracts import (
    CompileTransformationInput,
    CreateTransformationInput,
    ExecuteTransformationInput,
    RunTestsInput,
    TransformationFile,
    TransformationProjectRef,
)
from aide.connectors.dbt.namespace import snowflake_dbt_query_tag, snowflake_workflow_schema
from aide.connectors.dbt.real import build_real_snowflake
from aide.connectors.dbt.workspace import invocation_dir, profiles_dir, repository_root
from aide.connectors.snowflake.config import ROLE_DEVELOPMENT
from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.connectors.snowflake.real import RealSnowflakeConnector
from aide.connectors.snowflake.session import SnowflakeSession
from aide.domain.failures import FailureClass
from aide.domain.sql import SqlText

pytestmark = [
    pytest.mark.dbt_live,
    pytest.mark.skipif(
        not snowflake_dbt_credentials_available(),
        reason="Snowflake DEV dbt credentials unavailable",
    ),
]

RO_BUDGET = Budget(max_rows=32, max_bytes=65536, max_seconds=60)
BILLING_SOURCES = ("billing.customers", "billing.invoices")


def _live_context(*, workflow_id: UUID, label: str, deadline_seconds: int = 300) -> CallContext:
    return make_context(
        workflow_id=workflow_id,
        operation_idempotency_key=unique_key(label),
        deadline_seconds=deadline_seconds,
    )


def _scalar(row: dict[str, Any]) -> Any:
    return next(iter(row.values()))


async def _dev_call[T](context: CallContext, fn: Callable[[SnowflakeSession], T]) -> T:
    connector = RealSnowflakeConnector(SNOWFLAKE_DEV)
    try:
        return await connector._session_call(context, fn)  # noqa: SLF001
    finally:
        await connector.close()


async def _dev_rows(context: CallContext, sql: str) -> list[dict[str, Any]]:
    def run(session: SnowflakeSession) -> list[dict[str, Any]]:
        _columns, rows, _query_id = session.execute(sql)
        return rows

    return await _dev_call(context, run)


async def _drop_dbt_schema(context: CallContext, schema: str) -> None:
    if not schema.startswith("WF") or not schema.endswith("_DBT"):
        raise AssertionError("refusing to drop a non-workflow dbt schema")
    quoted = schema.replace('"', '""')
    await _dev_rows(context, f'DROP SCHEMA IF EXISTS AIDE_DEV."{quoted}" CASCADE')


def _qualified(schema: str, table: str) -> str:
    return f"AIDE_DEV.{schema}.{table}"


def _load_billing_into_schema(session: SnowflakeSession, schema: str) -> dict[str, int]:
    """Copy tiny v2 billing CSVs into AIDE_DEV.<schema>. Never touches VANTARA_RAW."""
    csv_root = repository_root() / "synthetic" / "vantara" / "fixtures" / "tiny" / "v2" / "csv"
    session.execute(f"CREATE SCHEMA IF NOT EXISTS AIDE_DEV.{schema}")
    loaded: dict[str, int] = {}
    for table_key in BILLING_SOURCES:
        table_def = TABLES[table_key]
        columns = columns_for_v2(table_key, table_def.columns)
        col_sql = ", ".join(f"{col.name} {snowflake_type(col.duckdb_type)}" for col in columns)
        qualified = _qualified(schema, table_def.name)
        stage = f"@AIDE_DEV.{schema}.%{table_def.name}"
        csv_path = (csv_root / csv_relative_path(table_def.schema, table_def.name)).resolve()
        if not csv_path.is_file():
            raise AssertionError(f"missing local fixture CSV for {table_key}")
        session.execute(f"CREATE OR REPLACE TABLE {qualified} ({col_sql})")
        session.execute(f"PUT '{csv_path.as_uri()}' {stage} AUTO_COMPRESS=FALSE OVERWRITE=TRUE")
        session.execute(
            f"COPY INTO {qualified} FROM {stage} "
            f"FILE_FORMAT=({COPY_FILE_FORMAT}) ON_ERROR='ABORT_STATEMENT'"
        )
        _cols, rows, _qid = session.execute(f"SELECT COUNT(*) AS N FROM {qualified}")
        loaded[table_def.name] = int(_scalar(rows[0]))
    return loaded


async def _ro_query(context: CallContext, sql: str) -> ExecuteQueryOutput:
    connector = RealSnowflakeConnector(SNOWFLAKE_RO)
    try:
        return await connector.execute_query(
            ExecuteQueryInput(
                sql=SqlText(dialect="snowflake", text=sql),
                budget=RO_BUDGET,
            ),
            context,
        )
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_live_dbt_snowflake_debug_parse_compile_run_test_isolate_fail_cleanup(
    tmp_path: Path,
) -> None:
    dbt = build_real_snowflake(tmp_path)
    workflow_a = uuid4()
    workflow_b = uuid4()
    schema_a = snowflake_workflow_schema(workflow_a)
    schema_b = snowflake_workflow_schema(workflow_b)
    assert schema_a != schema_b
    print(f"LIVE_DBT_SCHEMA_A={schema_a}")
    print(f"LIVE_DBT_SCHEMA_B={schema_b}")
    try:
        snapshot = await dbt.health()
        assert snapshot.status == "AVAILABLE", snapshot.reason_codes
        assert snapshot.reason_codes == ()

        debug_ctx = _live_context(workflow_id=workflow_a, label="debug")
        debug = await dbt.debug(debug_ctx)
        assert debug.exit_code == 0, debug.stderr or debug.stdout

        parse_ctx = _live_context(workflow_id=workflow_a, label="parse")
        parsed = await dbt.parse(parse_ctx)
        assert parsed.exit_code == 0, parsed.stderr or parsed.stdout

        compile_ctx = _live_context(workflow_id=workflow_a, label="compile")
        compiled = await dbt.compile_transformation(
            CompileTransformationInput(project_state_id=uuid4()),
            compile_ctx,
        )
        assert compiled.ok
        assert compiled.compiled
        assert compiled.manifest_ref is not None
        assert any(item.model == "fct_invoices" for item in compiled.compiled)
        invoices_sql = next(
            item.compiled_sql or ""
            for item in compiled.compiled
            if item.model == "stg_billing__invoices"
        )
        assert schema_a in invoices_sql
        assert "AIDE_DEV" in invoices_sql
        assert "VANTARA_RAW" not in invoices_sql
        assert "STATUS" in invoices_sql.upper()

        profiles = (profiles_dir(tmp_path, workflow_a) / "profiles.yml").read_text(encoding="utf-8")
        assert "env_var('SNOWFLAKE_ACCOUNT')" in profiles
        assert "env_var('SNOWFLAKE_USER_DEV')" in profiles
        assert "env_var('SNOWFLAKE_PRIVATE_KEY_DEV')" in profiles
        assert "env_var('SNOWFLAKE_WAREHOUSE_DEV')" in profiles
        assert "database: AIDE_DEV" in profiles
        assert f"schema: {schema_a}" in profiles
        assert f'query_tag: "{snowflake_dbt_query_tag(workflow_a)}"' in profiles
        assert "BEGIN" not in profiles
        assert "PRIVATE KEY" not in profiles

        role_ctx = _live_context(workflow_id=workflow_a, label="role")
        role_rows = await _dev_rows(role_ctx, "SELECT CURRENT_ROLE() AS ROLE")
        current_role = str(_scalar(role_rows[0]))
        print(f"LIVE_DBT_ROLE={current_role}")
        assert current_role.upper() == ROLE_DEVELOPMENT

        with pytest.raises(SnowflakeMappedError):
            await _dev_rows(role_ctx, "SELECT COUNT(*) AS N FROM VANTARA_RAW.BILLING.INVOICES")

        ro_ctx = _live_context(workflow_id=workflow_a, label="ro-source")
        raw_invoices = await _ro_query(
            ro_ctx, "SELECT COUNT(*) AS N FROM VANTARA_RAW.BILLING.INVOICES"
        )
        assert raw_invoices.rows
        assert int(_scalar(raw_invoices.rows[0])) > 0

        loaded_a = await _dev_call(
            _live_context(workflow_id=workflow_a, label="load-a"),
            lambda session: _load_billing_into_schema(session, schema_a),
        )
        assert loaded_a["CUSTOMERS"] > 0
        assert loaded_a["INVOICES"] > 0

        run_ctx = _live_context(workflow_id=workflow_a, label="run")
        executed = await dbt.execute_transformation(
            ExecuteTransformationInput(project_state_id=uuid4()),
            run_ctx,
        )
        assert executed.ok, executed.results
        assert executed.run_results_ref is not None

        test_ctx = _live_context(workflow_id=workflow_a, label="test")
        tests = await dbt.run_tests(
            RunTestsInput(project_state_id=uuid4()),
            test_ctx,
        )
        assert tests.ok
        assert tests.tests
        assert all(item.status in {"pass", "warn"} for item in tests.tests)

        run_inv = invocation_dir(
            tmp_path, workflow_a, run_ctx.operation_idempotency_key, run_ctx.attempt_id
        )
        manifest = parse_manifest(run_inv / "target" / "manifest.json")
        assert "model.vantara_project.fct_invoices" in manifest["nodes"]
        run_results = parse_run_results(run_inv / "target" / "run_results.json")
        assert any(
            "fct_invoices" in str(item.get("unique_id"))
            for item in run_results["results"]
            if isinstance(item, dict)
        )
        compiled_sql = list((run_inv / "target" / "compiled").rglob("*.sql"))
        assert compiled_sql
        invocation = (run_inv / "invocation.json").read_text(encoding="utf-8")
        assert '"execution_status": "COMPLETED"' in invocation
        assert "manifest.json" in invocation
        assert "run_results.json" in invocation
        journal = (run_inv / "journal.jsonl").read_text(encoding="utf-8")
        assert schema_a in journal
        assert snowflake_dbt_query_tag(workflow_a) in journal
        env_keys = (run_inv / "env_keys.json").read_text(encoding="utf-8")
        assert "SNOWFLAKE_USER_DEV" in env_keys
        assert "BEGIN" not in env_keys

        recovered = await dbt.reconcile(recovery_for(run_ctx, "execute_transformation"))
        assert isinstance(recovered, EffectFound)
        assert recovered.output.get("ok") is True

        count_rows = await _dev_rows(
            run_ctx,
            f"SELECT COUNT(*) AS N FROM {_qualified(schema_a, 'FCT_INVOICES')}",
        )
        assert int(_scalar(count_rows[0])) > 0

        raw_hits = await _ro_query(
            _live_context(workflow_id=workflow_a, label="ro-no-write"),
            "SELECT TABLE_NAME FROM VANTARA_RAW.INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = 'BILLING' AND TABLE_NAME IN "
            "('FCT_INVOICES','STG_BILLING__CUSTOMERS','STG_BILLING__INVOICES')",
        )
        assert not raw_hits.rows
        assert raw_hits.row_count == 0

        compile_b_ctx = _live_context(workflow_id=workflow_b, label="compile-b")
        compiled_b = await dbt.compile_transformation(
            CompileTransformationInput(project_state_id=uuid4()),
            compile_b_ctx,
        )
        assert compiled_b.ok
        loaded_b = await _dev_call(
            _live_context(workflow_id=workflow_b, label="load-b"),
            lambda session: _load_billing_into_schema(session, schema_b),
        )
        assert loaded_b["INVOICES"] > 0
        run_b_ctx = _live_context(workflow_id=workflow_b, label="run-b")
        executed_b = await dbt.execute_transformation(
            ExecuteTransformationInput(project_state_id=uuid4()),
            run_b_ctx,
        )
        assert executed_b.ok
        profiles_b = (profiles_dir(tmp_path, workflow_b) / "profiles.yml").read_text(
            encoding="utf-8"
        )
        assert f"schema: {schema_b}" in profiles_b
        assert f"schema: {schema_a}" not in profiles_b
        schema_rows = await _dev_rows(
            run_b_ctx,
            "SELECT SCHEMA_NAME FROM AIDE_DEV.INFORMATION_SCHEMA.SCHEMATA "
            f"WHERE SCHEMA_NAME IN ('{schema_a}','{schema_b}')",
        )
        names = {str(_scalar(row)) for row in schema_rows}
        assert schema_a in names
        assert schema_b in names

        fail_workflow = uuid4()
        fail_create_ctx = _live_context(workflow_id=fail_workflow, label="fail-create")
        created_fail = await dbt.create_transformation(
            CreateTransformationInput(
                files=(
                    TransformationFile(
                        path="models/staging/stg_live_compile_fail.sql",
                        content="select {{ definitely_not_a_macro() }} as id\n",
                    ),
                ),
                project_ref=TransformationProjectRef(project_id="vantara"),
            ),
            fail_create_ctx,
        )
        fail_compile_ctx = _live_context(workflow_id=fail_workflow, label="fail-compile")
        failed = await dbt.compile_transformation(
            CompileTransformationInput(
                project_state_id=created_fail.project_state_id,
                select=("stg_live_compile_fail",),
            ),
            fail_compile_ctx,
        )
        assert failed.ok is False
        assert failed.errors
        assert failed.errors[0].error_class is FailureClass.DBT_COMPILE
        fail_recovered = await dbt.reconcile(
            recovery_for(fail_compile_ctx, "compile_transformation")
        )
        assert isinstance(fail_recovered, EffectFound)
        assert fail_recovered.output.get("ok") is False

        for schema in (schema_a, schema_b):
            await _drop_dbt_schema(_live_context(workflow_id=workflow_a, label="cleanup"), schema)
        remaining = await _dev_rows(
            _live_context(workflow_id=workflow_a, label="cleanup-check"),
            "SELECT SCHEMA_NAME FROM AIDE_DEV.INFORMATION_SCHEMA.SCHEMATA "
            f"WHERE SCHEMA_NAME IN ('{schema_a}','{schema_b}')",
        )
        assert remaining == []
    finally:
        for schema in (schema_a, schema_b):
            with contextlib.suppress(Exception):
                await _drop_dbt_schema(
                    _live_context(workflow_id=workflow_a, label="cleanup-final"),
                    schema,
                )
        await dbt.close()
