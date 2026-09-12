from __future__ import annotations

import csv

import pytest

from aide.connectors.snowflake.fake import FakeSnowflakeConnector
from aide.profiling.artifacts import ProfilingFact, ProfilingRunResult
from aide.profiling.engine import profile_selected_assets
from aide.profiling.fixtures import TINY_FIXTURE_ROOT, demo_selected_assets
from aide.profiling.masking import looks_like_raw_email, looks_like_raw_phone


def _fact(result: ProfilingRunResult, fact_id: str) -> ProfilingFact:
    match = next((item for item in result.summary.facts if item.fact_id == fact_id), None)
    assert match is not None, f"missing fact {fact_id}"
    return match


def _first_contact_pii() -> tuple[str, str]:
    path = TINY_FIXTURE_ROOT / "v2" / "csv" / "crm" / "contacts.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
    return str(row["EMAIL"]), str(row["PHONE"])


@pytest.mark.asyncio
async def test_p1_duplicate_domain_evidence(vantara_v2: FakeSnowflakeConnector) -> None:
    result = await profile_selected_assets(vantara_v2, demo_selected_assets(), fixture_version="v2")
    fact = _fact(result, "P1_duplicate_accounts")
    assert isinstance(fact.value, float)
    assert fact.value < 1.0
    accounts = next(
        item for item in result.profiles if item.asset.address == ("VANTARA_RAW", "CRM", "ACCOUNTS")
    )
    domain = next(item for item in accounts.duplicate_evidence if "WEBSITE_DOMAIN" in item.columns)
    assert domain.duplicate_groups_estimate > 0
    assert any(
        item.expression and "WEBSITE_DOMAIN" in item.columns for item in accounts.key_evidence
    )
    assert any(key.columns == ("ACCOUNT_ID",) for key in accounts.candidate_keys)


@pytest.mark.asyncio
async def test_p3_crosswalk_and_orphan_relationships(vantara_v2: FakeSnowflakeConnector) -> None:
    result = await profile_selected_assets(vantara_v2, demo_selected_assets(), fixture_version="v2")
    p3 = _fact(result, "P3_crm_billing_crosswalk")
    assert isinstance(p3.value, float)
    assert 0.9 <= p3.value < 1.0
    crosswalk = next(
        item
        for item in result.relationships
        if item.known_pair
        and item.candidate.from_asset.address == ("VANTARA_RAW", "CRM", "ACCOUNT_CROSSWALK")
        and item.candidate.to_asset.address == ("VANTARA_RAW", "BILLING", "CUSTOMERS")
    )
    assert crosswalk.candidate.inclusion_ratio <= 1.0
    assert crosswalk.candidate.confidence >= crosswalk.candidate.inclusion_ratio
    assert "missing" in crosswalk.reason
    orphans = _fact(result, "P5_orphan_contacts")
    assert isinstance(orphans.value, float)
    assert orphans.value > 0
    unknown = _fact(result, "P5_unknown_invoice_customers")
    assert isinstance(unknown.value, float)
    assert unknown.value < 1.0


@pytest.mark.asyncio
async def test_p10_v1_unique_and_v2_duplicate_payments(
    vantara_v1: FakeSnowflakeConnector, vantara_v2: FakeSnowflakeConnector
) -> None:
    selected = demo_selected_assets()
    v1 = await profile_selected_assets(vantara_v1, selected, fixture_version="v1")
    v2 = await profile_selected_assets(vantara_v2, selected, fixture_version="v2")
    grain_v1 = _fact(v1, "P10_payment_grain")
    grain_v2 = _fact(v2, "P10_payment_grain")
    assert grain_v1.value == 1.0
    assert isinstance(grain_v2.value, float)
    assert grain_v2.value < 1.0
    payments_v2 = next(
        item
        for item in v2.profiles
        if item.asset.address == ("VANTARA_RAW", "PAYMENTS", "PAYMENTS")
    )
    dup = next(
        item
        for item in payments_v2.duplicate_evidence
        if item.columns == ("INVOICE_ID", "PAYMENT_REF")
    )
    assert dup.extra_row_estimate > 0
    payments_v1 = next(
        item
        for item in v1.profiles
        if item.asset.address == ("VANTARA_RAW", "PAYMENTS", "PAYMENTS")
    )
    assert payments_v1.row_count < payments_v2.row_count


@pytest.mark.asyncio
async def test_pii_is_masked_in_samples_and_top_values(vantara_v2: FakeSnowflakeConnector) -> None:
    email, phone = _first_contact_pii()
    result = await profile_selected_assets(vantara_v2, demo_selected_assets(), fixture_version="v2")
    encoded = result.model_dump_json()
    assert email not in encoded
    assert phone not in encoded
    contacts = next(
        item for item in result.profiles if item.asset.address == ("VANTARA_RAW", "CRM", "CONTACTS")
    )
    email_col = next(item for item in contacts.columns if item.name == "EMAIL")
    for top in email_col.top_values:
        assert not looks_like_raw_email(top.value_masked)
        assert top.value_masked is None or "***" in str(top.value_masked)
    contact_sample = next(
        item for item in result.samples if item.asset.address == ("VANTARA_RAW", "CRM", "CONTACTS")
    )
    assert "EMAIL" in contact_sample.masked_columns
    for row in contact_sample.rows:
        assert not looks_like_raw_email(row.get("EMAIL"))
        assert not looks_like_raw_phone(row.get("PHONE"))


@pytest.mark.asyncio
async def test_candidate_keys_and_relationship_confidence(
    vantara_v2: FakeSnowflakeConnector,
) -> None:
    result = await profile_selected_assets(vantara_v2, demo_selected_assets(), fixture_version="v2")
    invoices = next(
        item
        for item in result.profiles
        if item.asset.address == ("VANTARA_RAW", "BILLING", "INVOICES")
    )
    assert any(key.columns == ("INVOICE_ID",) for key in invoices.candidate_keys)
    for item in result.relationships:
        assert 0 <= item.candidate.confidence <= 1
        assert 0 <= item.candidate.inclusion_ratio <= 1
        assert item.reason
    known = [item for item in result.relationships if item.known_pair]
    assert known
    assert all(item.candidate.confidence >= 0 for item in known)


@pytest.mark.asyncio
async def test_does_not_profile_excluded_assets(vantara_v2: FakeSnowflakeConnector) -> None:
    result = await profile_selected_assets(vantara_v2, demo_selected_assets(), fixture_version="v2")
    profiled = {item.asset.address for item in result.profiles}
    assert ("VANTARA_RAW", "CRM", "OPPORTUNITIES") not in profiled
    assert ("VANTARA_RAW", "SUPPORT", "TICKETS") not in profiled
    assert len(result.profiles) == 10
    assert len(result.samples) == 3
    sampled = {item.asset.address for item in result.samples}
    assert ("VANTARA_RAW", "CRM", "ACCOUNTS") in sampled
    assert ("VANTARA_RAW", "CRM", "CONTACTS") in sampled
    assert ("VANTARA_RAW", "PAYMENTS", "PAYMENTS") in sampled
    assert all(item.row_count <= 20 for item in result.samples)
