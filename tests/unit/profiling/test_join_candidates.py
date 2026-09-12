from __future__ import annotations

from uuid import uuid4

from aide.capabilities.io import ProfileColumn
from aide.domain.sql import AssetKind, AssetRef
from aide.profiling.artifacts import DatasetProfileArtifact, MaskingState
from aide.profiling.fixtures import KNOWN_RELATIONSHIP_PAIRS
from aide.profiling.join_candidates import (
    join_rank_score,
    rank_join_candidates,
    select_join_candidates_for_measurement,
)
from aide.profiling.semantics import names_related, types_compatible


def test_join_rank_prefers_name_related_and_unique_parents() -> None:
    related = join_rank_score(
        name_related=True,
        from_semantic="ID",
        to_semantic="ID",
        from_uniqueness=0.2,
        to_uniqueness=1.0,
    )
    unrelated = join_rank_score(
        name_related=False,
        from_semantic="ID",
        to_semantic="ID",
        from_uniqueness=0.2,
        to_uniqueness=1.0,
    )
    assert related > unrelated


def test_customer_id_matches_billing_customer_id() -> None:
    assert names_related("CUSTOMER_ID", "BILLING_CUSTOMER_ID")
    assert names_related("ACCOUNT_ID", "CRM_ACCOUNT_ID")
    assert types_compatible("VARCHAR", "UUID")
    assert types_compatible("NUMBER", "NUMBER")


def test_evaluation_baseline_pairs_are_name_related() -> None:
    for _from_addr, from_col, _to_addr, to_col in KNOWN_RELATIONSHIP_PAIRS:
        assert names_related(from_col, to_col)


def _profile(
    address: tuple[str, str, str],
    columns: tuple[tuple[str, str, float], ...],
    types: tuple[tuple[str, str], ...] | None = None,
) -> DatasetProfileArtifact:
    asset = AssetRef(
        connector_id="snowflake_ro",
        address=address,
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    profile_columns = tuple(
        ProfileColumn(
            name=name,
            null_ratio=0.0,
            distinct_ratio=uniqueness,
            inferred_semantic=semantic,  # type: ignore[arg-type]
        )
        for name, semantic, uniqueness in columns
    )
    column_types = types or tuple((name, "VARCHAR") for name, _semantic, _uniq in columns)
    return DatasetProfileArtifact(
        fixture_version="test",
        asset=asset,
        profile_id=uuid4(),
        describe_snapshot_id=None,
        capability_profile_id=None,
        row_count=10,
        sampled=False,
        columns=profile_columns,
        candidate_keys=(),
        key_evidence=(),
        duplicate_evidence=(),
        duplicate_groups_estimate=0,
        masking=MaskingState(samples_masked=True, top_values_masked=True),
        column_types=column_types,
    )


def test_rank_join_prefers_name_related_customer_pair() -> None:
    child = _profile(
        ("VANTARA_RAW", "BILLING", "CUSTOMERS"),
        (("CUSTOMER_ID", "ID", 0.4), ("CRM_ACCOUNT_ID", "ID", 0.9)),
    )
    parent = _profile(
        ("VANTARA_RAW", "CRM", "ACCOUNT_CROSSWALK"),
        (("ACCOUNT_ID", "ID", 1.0), ("BILLING_CUSTOMER_ID", "ID", 1.0)),
    )
    ranked = rank_join_candidates((child, parent))
    assert ranked
    top = next(
        item
        for item in ranked
        if item.from_column == "CUSTOMER_ID" and item.to_column == "BILLING_CUSTOMER_ID"
    )
    other = next(
        item
        for item in ranked
        if item.from_column == "CUSTOMER_ID" and item.to_column == "ACCOUNT_ID"
    )
    assert top.name_related is True
    assert other.name_related is False
    assert top.rank_score > other.rank_score


def test_measurement_queue_keeps_name_related_when_max_pairs_is_one() -> None:
    child = _profile(
        ("RAW", "SALES", "ORDERS"),
        (("CUSTOMER_ID", "ID", 0.2),),
        types=(("CUSTOMER_ID", "NUMBER"),),
    )
    related_parent = _profile(
        ("RAW", "SALES", "CUSTOMERS"),
        (("CUSTOMER_ID", "ID", 1.0),),
        types=(("CUSTOMER_ID", "NUMBER"),),
    )
    unrelated_parent = _profile(
        ("RAW", "CRM", "ACCOUNTS"),
        (("ACCOUNT_ID", "ID", 1.0),),
        types=(("ACCOUNT_ID", "NUMBER"),),
    )
    queued = select_join_candidates_for_measurement(
        (child, related_parent, unrelated_parent), max_pairs=1
    )
    assert len(queued) == 1
    assert queued[0].name_related is True
    assert queued[0].from_column == "CUSTOMER_ID"
    assert queued[0].to_column == "CUSTOMER_ID"


def test_rank_join_skips_incompatible_types() -> None:
    child = _profile(
        ("RAW", "SALES", "ORDERS"),
        (("CUSTOMER_ID", "ID", 0.5),),
        types=(("CUSTOMER_ID", "NUMBER"),),
    )
    parent = _profile(
        ("RAW", "CRM", "ACCOUNTS"),
        (("ACCOUNT_ID", "ID", 1.0),),
        types=(("ACCOUNT_ID", "VARCHAR"),),
    )
    assert rank_join_candidates((child, parent)) == ()
