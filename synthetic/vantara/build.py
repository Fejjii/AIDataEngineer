"""Fixture build orchestration for Vantara synthetic data."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from synthetic.vantara.config import DEFAULT_SEED, PACKAGE_ROOT, Profile, profile_config
from synthetic.vantara.export.csv_export import export_csv_fixtures
from synthetic.vantara.export.duckdb_export import export_duckdb_fixture
from synthetic.vantara.export.expected_export import build_expected_metadata, write_expected_files
from synthetic.vantara.export.postgres_export import write_postgres_artifacts
from synthetic.vantara.export.snowflake_export import write_snowflake_loader
from synthetic.vantara.generate import generate_dataset


@dataclass(frozen=True, slots=True)
class BuildResult:
    profile: str
    seed: int
    total_rows: int
    build_seconds: float
    duckdb_hashes: dict[str, str]
    expected_dir: Path
    output_root: Path
    metadata: dict[str, Any]


def build_fixtures(
    profile: Profile | str,
    *,
    seed: int = DEFAULT_SEED,
    output_root: Path | None = None,
) -> BuildResult:
    config = profile_config(profile, seed=seed, output_root=output_root)
    started = time.perf_counter()
    dataset = generate_dataset(config)

    csv_hashes: dict[str, dict[str, str]] = {}
    duckdb_hashes: dict[str, str] = {}
    for version in ("v1", "v2"):
        version_dir = config.output_root / version
        csv_dir = version_dir / "csv"
        csv_hashes[version] = export_csv_fixtures(dataset, config, version, csv_dir)
        duckdb_path = version_dir / "vantara_raw.duckdb"
        duckdb_hashes[version] = export_duckdb_fixture(
            dataset,
            config,
            version,
            duckdb_path,
            csv_dir=csv_dir,
        )
        write_postgres_artifacts(config, version, config.output_root)

    write_snowflake_loader(config.profile.value, config.output_root)

    elapsed = time.perf_counter() - started
    metadata = build_expected_metadata(
        dataset,
        config,
        csv_hashes=csv_hashes,
        duckdb_hashes=duckdb_hashes,
        build_seconds=elapsed,
    )
    expected_dir = write_expected_files(metadata, config, PACKAGE_ROOT)

    manifest_path = config.output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return BuildResult(
        profile=config.profile.value,
        seed=seed,
        total_rows=int(metadata["actual_total_rows"]),
        build_seconds=elapsed,
        duckdb_hashes=duckdb_hashes,
        expected_dir=expected_dir,
        output_root=config.output_root,
        metadata=metadata,
    )
