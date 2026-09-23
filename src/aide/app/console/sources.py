"""Selected synthetic source tables for the operator console.

Samples are read from the committed tiny fixture, masked, and capped.
They are the scenario inputs, not expected mart rows.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml
from synthetic.vantara.schema import TABLES

from aide.connectors.snowflake.masking import mask_row
from aide.modelling.vantara import vantara_selected_addresses
from aide.profiling.fixtures import PII_COLUMNS_PATH, csv_path

_SAMPLE_ROWS = 5
_SAMPLE_COLUMNS = 8
_CELL_CAP = 64


@dataclass(frozen=True)
class SourceColumnView:
    name: str
    data_type: str
    nullable: bool


@dataclass(frozen=True)
class SourceTableView:
    address: str
    grain: str
    columns: tuple[SourceColumnView, ...]
    sample_columns: tuple[str, ...]
    sample_rows: tuple[tuple[str, ...], ...]
    sample_note: str


def load_source_catalog(
    *,
    fixture_root: Path | None = None,
    pii_path: Path | None = None,
) -> tuple[SourceTableView, ...]:
    sensitive = _sensitive_columns(pii_path or PII_COLUMNS_PATH)
    tables: list[SourceTableView] = []
    for database, schema, name in vantara_selected_addresses():
        definition = TABLES.get(f"{schema.lower()}.{name.lower()}")
        columns: tuple[SourceColumnView, ...] = ()
        grain = ""
        if definition is not None:
            columns = tuple(
                SourceColumnView(
                    name=column.name,
                    data_type=column.duckdb_type,
                    nullable=column.nullable,
                )
                for column in definition.columns
            )
            grain = definition.grain
        path = csv_path((database, schema, name), "v1")
        if fixture_root is not None:
            path = fixture_root / "v1" / "csv" / schema.lower() / f"{name.lower()}.csv"
        sample_columns, sample_rows, note = _sample(path, sensitive)
        tables.append(
            SourceTableView(
                address=f"{database}.{schema}.{name}",
                grain=grain,
                columns=columns,
                sample_columns=sample_columns,
                sample_rows=sample_rows,
                sample_note=note,
            )
        )
    return tuple(tables)


def _sensitive_columns(path: Path) -> set[str]:
    names: set[str] = set()
    if not path.is_file():
        return names
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return names
    columns = loaded.get("columns")
    if not isinstance(columns, list):
        return names
    for item in columns:
        if isinstance(item, dict) and isinstance(item.get("column"), str):
            names.add(item["column"].upper())
    return names


def _sample(
    path: Path, sensitive: set[str]
) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], str]:
    if not path.is_file():
        return (), (), "sample unavailable"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        if not fieldnames:
            return (), (), "sample unavailable"
        chosen = fieldnames[:_SAMPLE_COLUMNS]
        rows: list[tuple[str, ...]] = []
        for raw in reader:
            masked = mask_row(
                {name: raw.get(name) for name in chosen},
                sensitive=sensitive,
            )
            rows.append(tuple(_display(masked.get(name)) for name in chosen))
            if len(rows) >= _SAMPLE_ROWS:
                break
    return chosen, tuple(rows), f"capped at {_SAMPLE_ROWS} masked rows from the synthetic fixture"


def _display(value: object) -> str:
    if value is None or value == "":
        return "null"
    text = str(value)
    if len(text) > _CELL_CAP:
        return text[:_CELL_CAP]
    return text
