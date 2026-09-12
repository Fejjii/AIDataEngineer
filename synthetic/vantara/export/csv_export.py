"""CSV export for synthetic tables."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from synthetic.vantara.config import BAD_EXTRACT_DATE, ProfileConfig
from synthetic.vantara.generate import GeneratedDataset
from synthetic.vantara.schema import TABLES, invoice_columns_for_version


def _row_values(row: dict[str, Any], columns: tuple[str, ...]) -> list[Any]:
    values: list[Any] = []
    for col in columns:
        val = row.get(col)
        values.append("" if val is None else val)
    return values


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    columns: tuple[str, ...],
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row in rows:
            writer.writerow(_row_values(row, columns))
    return _file_sha256(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_csv_fixtures(
    dataset: GeneratedDataset,
    config: ProfileConfig,
    version: str,
    output_dir: Path,
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    invoice_rows = dataset.tables[f"billing.invoices_{version}"]

    for table_key, table_def in TABLES.items():
        if table_key.startswith("billing.invoices"):
            continue
        rows = dataset.tables.get(table_key, [])
        columns = tuple(col.name for col in table_def.columns)
        if table_key == "billing.invoice_lines" and version == "v1":
            # Bad extract day stores AMOUNT as VARCHAR (P8 / F1 companion).
            rows = [
                dict(row, AMOUNT=str(row["AMOUNT"]))
                if row.get("_EXTRACT_DATE") == BAD_EXTRACT_DATE
                else row
                for row in rows
            ]
        rel_path = Path(table_def.schema.lower()) / f"{table_def.name.lower()}.csv"
        file_hash = write_csv(output_dir / rel_path, rows, columns)
        hashes[str(rel_path)] = file_hash

    inv_columns = tuple(col.name for col in invoice_columns_for_version(version))
    inv_path = Path("billing") / "invoices.csv"
    hashes[str(inv_path)] = write_csv(output_dir / inv_path, invoice_rows, inv_columns)
    return hashes
