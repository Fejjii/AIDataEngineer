"""Expected metadata JSON for evaluation and tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from synthetic.vantara.config import (
    CROSSWALK_MISSING_RATE,
    DRIFT_EFFECTIVE_DATE,
    DUPLICATE_ACCOUNT_RATE,
    DUPLICATE_PAYMENT_RATE,
    NULL_CRM_ACCOUNT_ID_RATE,
    NULL_DUE_DATE_RATE,
    ORPHAN_CONTACT_RATE,
    UNKNOWN_INVOICE_CUSTOMER_RATE,
    ProfileConfig,
)
from synthetic.vantara.generate import GeneratedDataset


def _table_counts(dataset: GeneratedDataset) -> dict[str, int]:
    counts: dict[str, int] = {}
    for key, rows in dataset.tables.items():
        if key.endswith("_v2"):
            continue
        if key.endswith("_v1"):
            counts["billing.invoices"] = len(rows)
        else:
            counts[key] = len(rows)
    return counts


def build_expected_metadata(
    dataset: GeneratedDataset,
    config: ProfileConfig,
    *,
    csv_hashes: dict[str, dict[str, str]],
    duckdb_hashes: dict[str, str],
    build_seconds: float,
) -> dict[str, Any]:
    counts = _table_counts(dataset)
    total = sum(counts.values())
    return {
        "profile": config.profile.value,
        "seed": config.seed,
        "target_total_rows": config.target_total_rows,
        "actual_total_rows": total,
        "table_row_counts": counts,
        "build_seconds": round(build_seconds, 3),
        "file_hashes": {
            "csv": csv_hashes,
            "duckdb": duckdb_hashes,
        },
        "planted_problems": {
            "duplicate_account_rate_target": DUPLICATE_ACCOUNT_RATE,
            "duplicate_account_rate_actual": float(dataset.metrics.get("duplicate_account_rows", 0))
            / max(counts.get("crm.accounts", 1), 1),
            "orphan_contact_rate_target": ORPHAN_CONTACT_RATE,
            "orphan_contact_rate_actual": dataset.metrics.get("orphan_contact_rate"),
            "crosswalk_missing_rate_target": CROSSWALK_MISSING_RATE,
            "crosswalk_missing_rate_actual": dataset.metrics.get("crosswalk_missing_rate"),
            "unknown_invoice_customer_rate_target": UNKNOWN_INVOICE_CUSTOMER_RATE,
            "unknown_invoice_customer_rate_actual": dataset.metrics.get(
                "unknown_invoice_customer_rate"
            ),
            "null_crm_account_id_rate_target": NULL_CRM_ACCOUNT_ID_RATE,
            "null_crm_account_id_rate_actual": dataset.metrics.get("null_crm_account_id_rate"),
            "null_due_date_rate_target": NULL_DUE_DATE_RATE,
            "null_due_date_rate_actual": dataset.metrics.get("null_due_date_rate"),
            "duplicate_payment_rate_target": DUPLICATE_PAYMENT_RATE,
            "duplicate_payment_rate_actual": dataset.metrics.get("duplicate_payment_rate"),
        },
        "schema_drift": {
            "v1_status_column": "INVOICE_STATUS",
            "v2_status_column": "STATUS",
            "drift_effective_date": DRIFT_EFFECTIVE_DATE,
            "failure_scenarios": ["F1", "F2"],
        },
        "pii_columns_file": "pii_columns.yaml",
    }


def write_expected_files(
    metadata: dict[str, Any],
    config: ProfileConfig,
    package_root: Path,
) -> Path:
    expected_dir = package_root / "expected" / config.profile.value
    expected_dir.mkdir(parents=True, exist_ok=True)
    summary_path = expected_dir / "summary.json"
    summary_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    counts_path = expected_dir / "row_counts.json"
    counts_path.write_text(
        json.dumps(metadata["table_row_counts"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    problems_path = expected_dir / "planted_problems.json"
    problems_path.write_text(
        json.dumps(metadata["planted_problems"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return expected_dir
