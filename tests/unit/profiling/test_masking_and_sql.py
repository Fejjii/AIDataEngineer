from __future__ import annotations

import pytest

from aide.capabilities.io import SampleDatasetInput
from aide.domain.sql import AssetKind, AssetRef
from aide.profiling.budgets import ProfilingBudget, ProfilingBudgetExceeded
from aide.profiling.masking import (
    jsonable,
    looks_like_raw_email,
    looks_like_raw_phone,
    mask_value,
)
from aide.profiling.sql_templates import inclusion_sql, normalized_domain_sql

ORDERS = AssetRef(
    connector_id="snowflake_ro",
    address=("RAW", "SALES", "ORDERS"),
    kind=AssetKind.TABLE,
    platform_type="snowflake",
)


def test_mask_value_redacts_email_and_phone() -> None:
    assert mask_value("alice@example.com") == "a***@example.com"
    assert "***" in mask_value("+1-555-0100")
    assert looks_like_raw_email("alice@example.com")
    assert not looks_like_raw_email("a***@example.com")
    assert looks_like_raw_phone("+15550100")
    assert not looks_like_raw_phone("2023-01-01")
    assert jsonable(None) is None


def test_sql_templates_are_read_only_selects() -> None:
    domain = normalized_domain_sql(("VANTARA_RAW", "CRM", "ACCOUNTS"), "WEBSITE_DOMAIN")
    assert domain.startswith("SELECT")
    assert "REGEXP_REPLACE" in domain
    inclusion = inclusion_sql(
        ("VANTARA_RAW", "BILLING", "CUSTOMERS"),
        "CUSTOMER_ID",
        ("VANTARA_RAW", "CRM", "ACCOUNT_CROSSWALK"),
        "BILLING_CUSTOMER_ID",
    )
    assert "MINUS" in inclusion
    assert "CUSTOMER_ID" in inclusion


def test_sample_limit_contract() -> None:
    with pytest.raises(ProfilingBudgetExceeded):
        ProfilingBudget(
            max_rows=10,
            max_bytes=1000,
            max_seconds=5,
            max_queries=10,
            max_pairs=2,
            sample_n=21,
            sample_asset_limit=1,
            top_k=3,
        )
    allowed = SampleDatasetInput(asset=ORDERS, n=20)
    assert allowed.n == 20
