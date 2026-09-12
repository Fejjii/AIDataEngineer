"""Deterministic tests for the Vantara synthetic generator."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from pathlib import Path

import duckdb
import pytest
from synthetic.vantara.build import build_fixtures
from synthetic.vantara.config import (
    DEFAULT_SEED,
    DUPLICATE_ACCOUNT_RATE,
    DUPLICATE_PAYMENT_RATE,
    FULL_TABLE_VOLUMES,
    NULL_DUE_DATE_RATE,
    ORPHAN_CONTACT_RATE,
    PROFILE_TOTAL_TARGETS,
    UNKNOWN_INVOICE_CUSTOMER_RATE,
    Profile,
    profile_config,
)
from synthetic.vantara.export.duckdb_export import content_sha256, verify_duckdb_integrity
from synthetic.vantara.generate import generate_dataset
from synthetic.vantara.planted import (
    duplicate_payment_rate_v2,
    late_redelivery_duplicates,
    normalized_domain_duplicate_rate,
    normalized_domain_group_count,
    payment_grain_groups,
)
from synthetic.vantara.rng import normalize_domain

PACKAGE_ROOT = Path("synthetic/vantara")
PII_PATH = PACKAGE_ROOT / "pii_columns.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rate(actual: int, total: int) -> float:
    return actual / total if total else 0.0


def _assert_rate_close(actual: float, expected: float, tolerance: float, label: str) -> None:
    assert abs(actual - expected) <= tolerance, f"{label}: {actual} vs {expected}"


@pytest.mark.parametrize("profile", [Profile.TINY, Profile.DEMO, Profile.FULL])
def test_profile_volume_within_five_percent(profile: Profile) -> None:
    config = profile_config(profile)
    dataset = generate_dataset(config)
    total = int(dataset.metrics["total_rows"])
    target = PROFILE_TOTAL_TARGETS[profile]
    lower = target * 0.95
    upper = target * 1.05
    assert lower <= total <= upper, f"{profile}: {total} not in [{lower}, {upper}]"


@pytest.mark.parametrize("profile", [Profile.TINY, Profile.DEMO, Profile.FULL])
def test_normalized_domain_duplicate_rate_from_rows(profile: Profile) -> None:
    config = profile_config(profile)
    dataset = generate_dataset(config)
    accounts = dataset.tables["crm.accounts"]
    rate = normalized_domain_duplicate_rate(accounts)
    _assert_rate_close(rate, DUPLICATE_ACCOUNT_RATE, 0.015, f"{profile.value} duplicate rate")
    assert normalized_domain_group_count(accounts) >= 1
    for row in accounts:
        domain = row.get("WEBSITE_DOMAIN")
        assert domain
        assert normalize_domain(str(domain))


def test_same_seed_same_hashes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root_a = Path(tmp) / "a"
        root_b = Path(tmp) / "b"
        result_a = build_fixtures(Profile.TINY, seed=DEFAULT_SEED, output_root=root_a)
        result_b = build_fixtures(Profile.TINY, seed=DEFAULT_SEED, output_root=root_b)
        assert result_a.duckdb_hashes == result_b.duckdb_hashes
        for version in ("v1", "v2"):
            csv_a = sorted((root_a / version / "csv").rglob("*.csv"))
            csv_b = sorted((root_b / version / "csv").rglob("*.csv"))
            assert [_sha256(p) for p in csv_a] == [_sha256(p) for p in csv_b]


def test_v1_v2_schema_drift_columns() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixtures(Profile.TINY, output_root=root)
        for version, column in (("v1", "INVOICE_STATUS"), ("v2", "STATUS")):
            conn = duckdb.connect(str(root / version / "vantara_raw.duckdb"), read_only=True)
            cols = conn.execute('PRAGMA table_info("VANTARA_RAW"."BILLING"."INVOICES")').fetchall()
            names = {row[1] for row in cols}
            assert column in names
            other = "STATUS" if column == "INVOICE_STATUS" else "INVOICE_STATUS"
            assert other not in names
            conn.close()


def test_v1_v2_different_duckdb_fingerprints() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = build_fixtures(Profile.TINY, output_root=root)
        assert result.duckdb_hashes["v1"] != result.duckdb_hashes["v2"]
        v1_fp = content_sha256(root / "v1" / "vantara_raw.duckdb")
        v2_fp = content_sha256(root / "v2" / "vantara_raw.duckdb")
        assert v1_fp != v2_fp
        assert v1_fp == result.duckdb_hashes["v1"]
        assert v2_fp == result.duckdb_hashes["v2"]


def test_same_version_duckdb_fingerprint_is_stable() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixtures(Profile.TINY, output_root=root)
        v1_first = content_sha256(root / "v1" / "vantara_raw.duckdb")
        v1_second = content_sha256(root / "v1" / "vantara_raw.duckdb")
        assert v1_first == v1_second


def test_v1_has_no_late_payment_redelivery_duplicates() -> None:
    for profile in Profile:
        dataset = generate_dataset(profile_config(profile))
        payments_v1 = dataset.tables["payments.payments_v1"]
        assert late_redelivery_duplicates(payments_v1) == []
        groups = payment_grain_groups(payments_v1)
        assert all(len(rows) == 1 for rows in groups.values())


def test_v2_has_expected_duplicate_payment_groups() -> None:
    for profile in Profile:
        config = profile_config(profile)
        dataset = generate_dataset(config)
        payments_v1 = dataset.tables["payments.payments_v1"]
        payments_v2 = dataset.tables["payments.payments_v2"]
        assert len(payments_v2) > len(payments_v1)
        duplicate_rows = late_redelivery_duplicates(payments_v2)
        assert duplicate_rows
        groups = payment_grain_groups(payments_v2)
        duplicate_groups = [rows for rows in groups.values() if len(rows) > 1]
        assert duplicate_groups
        for rows in duplicate_groups:
            assert len({row["INVOICE_ID"] for row in rows}) == 1
            assert len({row["PAYMENT_REF"] for row in rows}) == 1
            loaded_times = [row["_LOADED_AT"] for row in rows]
            assert len(set(loaded_times)) == len(loaded_times)
            assert max(loaded_times) > min(loaded_times)
        base_grains = len(payment_grain_groups(payments_v1))
        _assert_rate_close(
            duplicate_payment_rate_v2(payments_v2),
            DUPLICATE_PAYMENT_RATE,
            0.002 if base_grains >= 100 else 0.02,
            f"{profile.value} v2 duplicate payment rate",
        )


def test_duplicate_payment_rate_invariant() -> None:
    for profile in Profile:
        config = profile_config(profile)
        dataset = generate_dataset(config)
        payment_base = config.table_volumes["payments.payments"]
        actual_rate = float(dataset.metrics["duplicate_payment_rate"])
        expected = DUPLICATE_PAYMENT_RATE
        assert abs(actual_rate - expected) <= 0.002 or payment_base < 100


def test_null_and_orphan_rates(profile: Profile = Profile.TINY) -> None:
    config = profile_config(profile)
    dataset = generate_dataset(config)
    orphan_rate = float(dataset.metrics["orphan_contact_rate"])
    assert abs(orphan_rate - ORPHAN_CONTACT_RATE) <= 0.005

    unknown_rate = float(dataset.metrics["unknown_invoice_customer_rate"])
    assert abs(unknown_rate - UNKNOWN_INVOICE_CUSTOMER_RATE) <= 0.002

    null_due_rate = float(dataset.metrics["null_due_date_rate"])
    assert abs(null_due_rate - NULL_DUE_DATE_RATE) <= 0.01


def test_pii_metadata_file() -> None:
    assert PII_PATH.is_file()
    content = PII_PATH.read_text(encoding="utf-8")
    assert "company: vantara" in content
    assert "column: EMAIL" in content
    assert "pii_type: email" in content


def test_expected_metadata_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = build_fixtures(Profile.TINY, output_root=Path(tmp))
        expected_dir = result.expected_dir
        for name in ("summary.json", "row_counts.json", "planted_problems.json"):
            path = expected_dir / name
            assert path.is_file(), name
            json.loads(path.read_text(encoding="utf-8"))


def test_duckdb_fixture_integrity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixtures(Profile.TINY, output_root=root)
        for version in ("v1", "v2"):
            counts = verify_duckdb_integrity(root / version / "vantara_raw.duckdb", version)
            assert counts["crm.accounts"] > 0
            assert counts["billing.invoices"] > 0
            status_key = "has_invoice_status" if version == "v1" else "has_status"
            assert counts[status_key] == 1
        v1_payments = duckdb.connect(str(root / "v1" / "vantara_raw.duckdb"), read_only=True)
        v2_payments = duckdb.connect(str(root / "v2" / "vantara_raw.duckdb"), read_only=True)
        v1_row = v1_payments.execute(
            'SELECT COUNT(*) FROM "VANTARA_RAW"."PAYMENTS"."PAYMENTS"'
        ).fetchone()
        v2_row = v2_payments.execute(
            'SELECT COUNT(*) FROM "VANTARA_RAW"."PAYMENTS"."PAYMENTS"'
        ).fetchone()
        assert v1_row is not None and v2_row is not None
        v1_count = int(v1_row[0])
        v2_count = int(v2_row[0])
        assert v2_count > v1_count
        v1_payments.close()
        v2_payments.close()


def test_csv_fixture_integrity() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        build_fixtures(Profile.TINY, output_root=root)
        invoices_csv = root / "v1" / "csv" / "billing" / "invoices.csv"
        with invoices_csv.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames: tuple[str, ...] = tuple(reader.fieldnames or ())
            rows = list(reader)
            assert "INVOICE_STATUS" in fieldnames
            assert len(rows) > 0
        lines_csv = root / "v1" / "csv" / "billing" / "invoice_lines.csv"
        with lines_csv.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            bad_rows = [row for row in reader if row.get("_EXTRACT_DATE") == "2026-06-15"]
            assert bad_rows, "expected bad extract day rows"
            assert all(row["AMOUNT"] for row in bad_rows)


def test_full_profile_generation_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = build_fixtures(Profile.FULL, output_root=Path(tmp))
        assert result.total_rows >= PROFILE_TOTAL_TARGETS[Profile.FULL] * 0.95
        assert (Path(tmp) / "v2" / "vantara_raw.duckdb").is_file()


def test_table_scaling_matches_full_profile_factor() -> None:
    tiny = profile_config(Profile.TINY).table_volumes
    for key, full_count in FULL_TABLE_VOLUMES.items():
        if key == "product.plans":
            assert tiny[key] == full_count
        else:
            assert tiny[key] == max(1, round(full_count * 0.005))
