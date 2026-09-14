"""Offline real dbt Core + DuckDB evaluation against Vantara tiny v1.

No Snowflake credentials. Marks as ``dbt_offline``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import duckdb
import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import build_tiny_v1_duckdb, unique_key

from aide.connectors.base.context import CallContext
from aide.connectors.dbt.artifacts import parse_manifest, parse_run_results
from aide.connectors.dbt.contracts import (
    CompileTransformationInput,
    ExecuteTransformationInput,
    RunTestsInput,
)
from aide.connectors.dbt.real import build_real_duckdb
from aide.connectors.dbt.runner import build_controlled_env
from aide.connectors.dbt.workspace import duckdb_workspace_path, invocation_dir

pytestmark = pytest.mark.dbt_offline

FORBIDDEN_SNOWFLAKE_ENV = (
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PASSWORD",
    "SNOWFLAKE_PRIVATE_KEY",
    "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
)


def _assert_no_snowflake_env() -> None:
    env = build_controlled_env({}, secret_names=())
    leaked = [name for name in FORBIDDEN_SNOWFLAKE_ENV if name in env]
    assert not leaked, leaked


def _count_model(duckdb_path: Path, model: str) -> int:
    conn = duckdb.connect(str(duckdb_path), read_only=True)
    try:
        rows = conn.execute("SHOW ALL TABLES").fetchall()
        for row in rows:
            name = str(row[2])
            if name.lower() == model.lower():
                catalog, schema, table = str(row[0]), str(row[1]), str(row[2])
                ident = f'"{catalog}"."{schema}"."{table}"'
                counted = conn.execute(f"SELECT COUNT(*) FROM {ident}").fetchone()
                return int(counted[0]) if counted is not None else 0
    finally:
        conn.close()
    raise AssertionError(f"model {model} not found in {duckdb_path}")


def _offline_context(*, workflow_id: UUID, label: str) -> CallContext:
    return make_context(
        workflow_id=workflow_id,
        operation_idempotency_key=unique_key(label),
        deadline_seconds=180,
    )


@pytest.mark.asyncio
async def test_offline_dbt_debug_parse_compile_run_test(tmp_path: Path) -> None:
    _assert_no_snowflake_env()
    duckdb_path = build_tiny_v1_duckdb(tmp_path / "vantara_raw.duckdb")
    connector = build_real_duckdb(tmp_path, duckdb_path=duckdb_path)
    workflow_id = uuid4()

    debug = await connector.debug(_offline_context(workflow_id=workflow_id, label="debug"))
    assert debug.exit_code == 0, debug.stderr or debug.stdout

    parse = await connector.parse(_offline_context(workflow_id=workflow_id, label="parse"))
    assert parse.exit_code == 0, parse.stderr or parse.stdout

    compile_ctx = _offline_context(workflow_id=workflow_id, label="compile")
    compiled = await connector.compile_transformation(
        CompileTransformationInput(project_state_id=uuid4()),
        compile_ctx,
    )
    assert compiled.ok
    assert compiled.compiled
    assert compiled.manifest_ref is not None
    assert any(item.model == "fct_invoices" for item in compiled.compiled)

    run_ctx = _offline_context(workflow_id=workflow_id, label="run")
    executed = await connector.execute_transformation(
        ExecuteTransformationInput(project_state_id=uuid4()),
        run_ctx,
    )
    assert executed.ok
    assert executed.results
    assert executed.run_results_ref is not None

    test_ctx = _offline_context(workflow_id=workflow_id, label="test")
    tests = await connector.run_tests(
        RunTestsInput(project_state_id=uuid4()),
        test_ctx,
    )
    assert tests.ok
    assert tests.tests
    assert all(item.status in {"pass", "warn"} for item in tests.tests)

    project = tmp_path / ".aide" / "work" / str(workflow_id) / "project"
    manifest = parse_manifest(project / "target" / "manifest.json")
    assert "model.vantara_project.fct_invoices" in manifest["nodes"]

    run_inv = invocation_dir(
        tmp_path, workflow_id, run_ctx.operation_idempotency_key, run_ctx.attempt_id
    )
    run_results = parse_run_results(run_inv / "target" / "run_results.json")
    assert any(
        "fct_invoices" in str(item.get("unique_id"))
        for item in run_results["results"]
        if isinstance(item, dict)
    )
    test_inv = invocation_dir(
        tmp_path, workflow_id, test_ctx.operation_idempotency_key, test_ctx.attempt_id
    )
    test_results = parse_run_results(test_inv / "target" / "run_results.json")
    assert any(
        str(item.get("unique_id", "")).startswith("test.") for item in test_results["results"]
    )

    capture = json.loads((run_inv / "invocation.json").read_text(encoding="utf-8"))
    assert capture["execution_status"] == "COMPLETED"
    assert "run_results.json" in capture["artifact_hashes"]
    assert "manifest.json" in capture["artifact_hashes"]

    workspace_db = duckdb_workspace_path(tmp_path, workflow_id)
    assert _count_model(workspace_db, "fct_invoices") == 6200
    assert _count_model(workspace_db, "stg_billing__customers") == 128

    dumped = (run_inv / "env_keys.json").read_text(encoding="utf-8")
    for name in FORBIDDEN_SNOWFLAKE_ENV:
        assert name not in dumped
    _assert_no_snowflake_env()
    await connector.close()


@pytest.mark.asyncio
async def test_offline_parallel_workflow_isolation(tmp_path: Path) -> None:
    duckdb_path = build_tiny_v1_duckdb(tmp_path / "vantara_raw.duckdb")
    connector = build_real_duckdb(tmp_path, duckdb_path=duckdb_path)

    async def _compile(label: str) -> str:
        workflow_id = uuid4()
        result = await connector.compile_transformation(
            CompileTransformationInput(project_state_id=uuid4()),
            _offline_context(workflow_id=workflow_id, label=label),
        )
        assert result.ok
        return str(workflow_id)

    first, second = await asyncio.gather(_compile("p1"), _compile("p2"))
    assert first != second
    assert (tmp_path / ".aide" / "work" / first / "project" / "target" / "manifest.json").is_file()
    assert (tmp_path / ".aide" / "work" / second / "project" / "target" / "manifest.json").is_file()
    await connector.close()
