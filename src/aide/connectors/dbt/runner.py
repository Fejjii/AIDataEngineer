"""Isolated dbt subprocess runner. No long-lived dbt state in the API process."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from aide.connectors.dbt.artifacts import write_text_artifact
from aide.connectors.dbt.errors import DbtProcessTerminatedError, DbtTimeoutError
from aide.connectors.dbt.redaction import env_keys_only, sanitize_text
from aide.connectors.dbt.workspace import invocation_dir as invocation_dir_for

PASSTHROUGH_ENV = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "USER",
    "TMPDIR",
    "TMP",
    "TEMP",
    "VIRTUAL_ENV",
    "PYTHONPATH",
    "PYTHONHOME",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
)


@dataclass(frozen=True, slots=True)
class IsolatedResult:
    exit_code: int
    timed_out: bool
    terminated: bool
    stdout: str
    stderr: str
    result_payload: dict[str, Any]
    invocation_dir: Path
    command: tuple[str, ...]


def build_controlled_env(
    extra: dict[str, str],
    *,
    secret_names: tuple[str, ...] = (),
) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in PASSTHROUGH_ENV:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["DBT_SEND_ANONYMOUS_USAGE_STATS"] = "false"
    env["DO_NOT_TRACK"] = "1"
    for name in secret_names:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    env.update(extra)
    try:
        from aide.connectors.dbt.workspace import repository_root

        root = repository_root()
        additions = [str(root / "src"), str(root)]
    except FileNotFoundError:
        additions = []
    existing = env.get("PYTHONPATH", "")
    existing_parts = existing.split(os.pathsep) if existing else []
    parts = [*additions, *existing_parts]
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(part for part in parts if part))
    return env


def run_isolated(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    invocation_dir: Path,
    extra_secrets: tuple[str, ...] = (),
    secret_names: tuple[str, ...] = (),
) -> IsolatedResult:
    """Run a subprocess with a hard timeout and sanitized captured logs."""
    invocation_dir.mkdir(parents=True, exist_ok=True)
    result_path = invocation_dir / "dbt_result.json"
    env = dict(env)
    env["AIDE_DBT_RESULT_PATH"] = str(result_path)
    (invocation_dir / "args.json").write_text(
        json.dumps({"command": command, "cwd": str(cwd)}, indent=2) + "\n",
        encoding="utf-8",
    )
    (invocation_dir / "env_keys.json").write_text(
        json.dumps(env_keys_only(env, secret_names=secret_names), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    timed_out = False
    terminated = False
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )
    try:
        raw_stdout, raw_stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        raw_stdout, raw_stderr = proc.communicate()
    stdout = sanitize_text(
        (raw_stdout or b"").decode("utf-8", errors="replace"),
        extra_secrets=extra_secrets,
    )
    stderr = sanitize_text(
        (raw_stderr or b"").decode("utf-8", errors="replace"),
        extra_secrets=extra_secrets,
    )
    write_text_artifact(invocation_dir / "stdout.log", stdout, extra_secrets=extra_secrets)
    write_text_artifact(invocation_dir / "stderr.log", stderr, extra_secrets=extra_secrets)
    exit_code = proc.returncode if proc.returncode is not None else -1
    if exit_code < 0:
        terminated = True
    payload: dict[str, Any] = {}
    if result_path.exists():
        loaded = json.loads(result_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
            message = payload.get("message")
            if isinstance(message, str):
                payload["message"] = sanitize_text(message, extra_secrets=extra_secrets)
    if timed_out:
        raise DbtTimeoutError("dbt invocation exceeded hard timeout")
    if terminated:
        raise DbtProcessTerminatedError("dbt process terminated", signal=-exit_code)
    return IsolatedResult(
        exit_code=exit_code,
        timed_out=timed_out,
        terminated=terminated,
        stdout=stdout,
        stderr=stderr,
        result_payload=payload,
        invocation_dir=invocation_dir,
        command=tuple(command),
    )


def dbt_cli_command(args: list[str]) -> list[str]:
    return [sys.executable, "-m", "aide.connectors.dbt.cli_entry", *args]


def run_dbt(
    args: list[str],
    *,
    work_root: Path,
    workflow_id: UUID,
    operation_idempotency_key: str,
    attempt_id: UUID,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    extra_secrets: tuple[str, ...] = (),
    secret_names: tuple[str, ...] = (),
) -> IsolatedResult:
    dest = invocation_dir_for(work_root, workflow_id, operation_idempotency_key, attempt_id)
    return run_isolated(
        dbt_cli_command(args),
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        invocation_dir=dest,
        extra_secrets=extra_secrets,
        secret_names=secret_names,
    )


def remaining_timeout_seconds(deadline_seconds: float, configured: int) -> float:
    return max(0.1, min(float(configured), deadline_seconds))
