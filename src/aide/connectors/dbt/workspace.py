"""Per-workflow dbt working copies under `.aide/work/<workflow_id>/project`."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from aide.connectors.dbt.contracts import TransformationFile, WrittenFile
from aide.connectors.dbt.errors import DbtMappedError
from aide.domain.failures import FailureClass

ALLOWED_SUFFIXES = {".sql", ".yml", ".yaml", ".md"}
FORBIDDEN_FILENAMES = frozenset({"dbt_project.yml", "profiles.yml"})
COPY_IGNORE = {"target", "dbt_packages", "logs", "__pycache__", ".git"}


def repository_root(start: Path | None = None) -> Path:
    starts: list[Path] = []
    if start is not None:
        starts.append(start)
    starts.append(Path(__file__).resolve())
    starts.append(Path.cwd())
    seen: set[Path] = set()
    for here in starts:
        anchor = here.parent if here.is_file() else here
        for parent in (anchor, *anchor.parents):
            resolved = parent.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if (resolved / "pyproject.toml").is_file() and (
                resolved / "dbt" / "vantara_project"
            ).is_dir():
                return resolved
    raise FileNotFoundError("repository root with dbt/vantara_project not found")


def default_project_template() -> Path:
    return repository_root() / "dbt" / "vantara_project"


def tiny_fixture_csv_root() -> Path:
    return repository_root() / "synthetic" / "vantara" / "fixtures" / "tiny" / "v1" / "csv"


def workflow_root(work_root: Path, workflow_id: UUID) -> Path:
    return Path(work_root) / ".aide" / "work" / str(workflow_id)


def project_dir(work_root: Path, workflow_id: UUID) -> Path:
    return workflow_root(work_root, workflow_id) / "project"


def profiles_dir(work_root: Path, workflow_id: UUID) -> Path:
    return workflow_root(work_root, workflow_id) / "profiles"


def invocation_dir(
    work_root: Path,
    workflow_id: UUID,
    operation_idempotency_key: str,
    attempt_id: UUID,
) -> Path:
    return (
        workflow_root(work_root, workflow_id)
        / "invocations"
        / operation_idempotency_key
        / str(attempt_id)
    )


def duckdb_workspace_path(work_root: Path, workflow_id: UUID) -> Path:
    return workflow_root(work_root, workflow_id) / "vantara_raw.duckdb"


def ensure_project_copy(template: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    shutil.copytree(template, destination, ignore=_ignore)
    return destination


def _ignore(directory: str, names: list[str]) -> set[str]:
    del directory
    return {name for name in names if name in COPY_IGNORE}


def confined_path(project_root: Path, relative: str) -> Path:
    candidate_raw = Path(relative)
    if candidate_raw.is_absolute() or ".." in candidate_raw.parts:
        raise DbtMappedError(FailureClass.UNSAFE_OPERATION, "path escape")
    resolved_root = project_root.resolve()
    candidate = (resolved_root / candidate_raw).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise DbtMappedError(FailureClass.UNSAFE_OPERATION, "path escape") from exc
    if candidate.name in FORBIDDEN_FILENAMES:
        raise DbtMappedError(
            FailureClass.UNSAFE_OPERATION,
            f"{candidate.name} is not writable by create_transformation",
        )
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise DbtMappedError(
            FailureClass.UNSAFE_OPERATION,
            f"disallowed extension {candidate.suffix}",
        )
    return candidate


def write_project_files(
    project_root: Path,
    files: Iterable[TransformationFile],
    *,
    mode: str,
) -> tuple[WrittenFile, ...]:
    written: list[WrittenFile] = []
    for item in files:
        target = confined_path(project_root, item.path)
        if mode == "ADD" and target.exists():
            raise DbtMappedError(FailureClass.UNSAFE_OPERATION, f"file already exists: {item.path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        data = item.content.encode("utf-8")
        target.write_text(item.content, encoding="utf-8")
        written.append(WrittenFile(path=item.path, sha256=hashlib.sha256(data).hexdigest()))
    return tuple(written)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
