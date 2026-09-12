from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from tests.connectors.contract.conftest import make_context
from tests.connectors.dbt_support import unique_key

from aide.connectors.dbt.errors import DbtTimeoutError
from aide.connectors.dbt.fake import FakeDbtConnector
from aide.connectors.dbt.redaction import sanitize_text
from aide.connectors.dbt.runner import build_controlled_env, run_isolated
from aide.connectors.dbt.specs import FAKE_DBT_DEV
from aide.connectors.dbt.workspace import project_dir


def test_workspace_path_is_workflow_isolated(tmp_path: Path) -> None:
    workflow_a = uuid4()
    workflow_b = uuid4()
    path_a = project_dir(tmp_path, workflow_a)
    path_b = project_dir(tmp_path, workflow_b)
    assert path_a != path_b
    assert path_a.as_posix().endswith(f".aide/work/{workflow_a}/project")
    assert path_b.as_posix().endswith(f".aide/work/{workflow_b}/project")


@pytest.mark.asyncio
async def test_parallel_fake_workspaces_do_not_collide(tmp_path: Path) -> None:
    from aide.connectors.dbt.contracts import (
        CompileTransformationInput,
        CreateTransformationInput,
        TransformationProjectRef,
    )

    async def compile_one(label: str) -> None:
        connector = FakeDbtConnector(FAKE_DBT_DEV, work_root=tmp_path)
        workflow_id = uuid4()
        created = await connector.create_transformation(
            CreateTransformationInput(
                files=(),
                project_ref=TransformationProjectRef(project_id=label),
            ),
            make_context(workflow_id=workflow_id, operation_idempotency_key=unique_key(label)),
        )
        compiled = await connector.compile_transformation(
            CompileTransformationInput(project_state_id=created.project_state_id),
            make_context(
                workflow_id=workflow_id,
                operation_idempotency_key=unique_key(label + "c"),
            ),
        )
        assert compiled.ok
        await connector.close()

    await asyncio.gather(compile_one("wf1"), compile_one("wf2"))


def test_subprocess_timeout_kills_process(tmp_path: Path) -> None:
    dest = tmp_path / "inv"
    with pytest.raises(DbtTimeoutError):
        run_isolated(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            cwd=tmp_path,
            env={"PATH": str(Path(sys.executable).parent), "HOME": str(tmp_path)},
            timeout_seconds=0.2,
            invocation_dir=dest,
        )
    assert (dest / "stdout.log").exists()
    assert (dest / "stderr.log").exists()


def test_secret_redaction_strips_values_keeps_names() -> None:
    raw = (
        "password=supersecretvalue99 token=abcdef123456 "
        "SNOWFLAKE_PRIVATE_KEY_DEV is the env var name"
    )
    cleaned = sanitize_text(raw, extra_secrets=("supersecretvalue99",))
    assert "supersecretvalue99" not in cleaned
    assert "SNOWFLAKE_PRIVATE_KEY_DEV" in cleaned
    assert "[REDACTED]" in cleaned


def test_controlled_env_omits_unlisted_snowflake_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "super-secret-pass")
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acct_should_not_passthrough")
    env = build_controlled_env(
        {"AIDE_DBT_DUCKDB_PATH": str(tmp_path / "x.duckdb")},
        secret_names=(),
    )
    assert "SNOWFLAKE_PASSWORD" not in env
    assert "SNOWFLAKE_ACCOUNT" not in env
    assert "super-secret-pass" not in str(env)
    assert "acct_should_not_passthrough" not in str(env)


def test_isolated_stdout_redacts_injected_secrets(tmp_path: Path) -> None:
    dest = tmp_path / "inv"
    result = run_isolated(
        [sys.executable, "-c", "print('visible secretvalue123 visible')"],
        cwd=tmp_path,
        env={"PATH": str(Path(sys.executable).parent), "HOME": str(tmp_path)},
        timeout_seconds=5,
        invocation_dir=dest,
        extra_secrets=("secretvalue123",),
    )
    assert result.exit_code == 0
    assert "secretvalue123" not in result.stdout
    assert "[REDACTED]" in result.stdout
    assert "secretvalue123" not in (dest / "stdout.log").read_text(encoding="utf-8")
