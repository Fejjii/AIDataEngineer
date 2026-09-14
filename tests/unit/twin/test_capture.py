from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aide.capabilities.io import (
    CatalogAsset,
    ColumnSpec,
    DescribeAssetOutput,
    DiscoverAssetsOutput,
    ProfileColumn,
)
from aide.domain.sql import AssetKind, AssetRef
from aide.domain.twin import SourceAuthorityRef, TwinAssetKind, TwinObservationKind
from aide.profiling.artifacts import (
    BudgetUsage,
    DatasetProfileArtifact,
    MaskingState,
    ProfilingRunResult,
    ProfilingSummary,
)
from aide.twin.capture import (
    capture_dbt_artifacts,
    capture_profile_observations,
    capture_snowflake_metadata,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def test_snowflake_capture_keeps_only_selected_physical_metadata() -> None:
    authority = SourceAuthorityRef(
        authority_id="snowflake_ro",
        contract_version="1.0",
        scope=("VANTARA_RAW", "BILLING"),
    )
    address = ("VANTARA_RAW", "BILLING", "INVOICES")
    discovered = DiscoverAssetsOutput(
        assets=(
            CatalogAsset(
                connector_id="snowflake_ro",
                address=address,
                kind=AssetKind.TABLE,
                platform_type="snowflake",
                row_count_estimate=10,
            ),
        ),
        snapshot_id=uuid4(),
    )
    described = DescribeAssetOutput(
        asset=AssetRef(
            connector_id="snowflake_ro",
            address=address,
            kind=AssetKind.TABLE,
            platform_type="snowflake",
        ),
        columns=(
            ColumnSpec(
                name="INVOICE_ID",
                data_type="NUMBER",
                nullable=False,
                ordinal=1,
            ),
            ColumnSpec(
                name="INVOICE_STATUS",
                data_type="VARCHAR",
                nullable=False,
                ordinal=2,
            ),
        ),
        primary_key=("INVOICE_ID",),
        row_count=10,
        snapshot_id=uuid4(),
    )

    batch = capture_snowflake_metadata(
        discovered=discovered,
        descriptions=(described,),
        source_authority=authority,
        evidence_ref_id=uuid4(),
        observed_at=NOW,
        fresh_until=NOW + timedelta(hours=1),
    )

    assert [item.kind for item in batch.assets] == [
        TwinAssetKind.DATASET,
        TwinAssetKind.FIELD,
        TwinAssetKind.FIELD,
    ]
    assert len(batch.relationships) == 2
    assert batch.observations[0].kind is TwinObservationKind.SCHEMA
    assert "rows" not in batch.model_dump_json().lower()


def test_dbt_capture_is_manifest_scoped_and_uses_declared_lineage() -> None:
    authority = SourceAuthorityRef(
        authority_id="dbt_core",
        contract_version="1.11",
        scope=("vantara",),
    )
    source_asset_id = uuid4()
    manifest = {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
            "project_id": "vantara",
        },
        "nodes": {
            "model.vantara.customer_revenue": {
                "resource_type": "model",
                "name": "customer_revenue",
                "package_name": "vantara",
                "database": "AIDE_DEV",
                "schema": "MVP001",
                "alias": "CUSTOMER_REVENUE",
                "original_file_path": "models/customer_revenue.sql",
                "config": {"materialized": "table"},
                "depends_on": {"nodes": ["source.vantara.invoices"]},
                "compiled_code": "select * from source_rows",
            },
            "test.vantara.not_null_customer_revenue_customer_id": {
                "resource_type": "test",
                "name": "not_null_customer_revenue_customer_id",
                "package_name": "vantara",
                "depends_on": {"nodes": ["model.vantara.customer_revenue"]},
            },
        },
    }
    run_results = {
        "results": [
            {
                "unique_id": "model.vantara.customer_revenue",
                "status": "success",
                "execution_time": 0.5,
            },
            {
                "unique_id": "test.vantara.not_null_customer_revenue_customer_id",
                "status": "pass",
                "failures": 0,
                "depends_on": {"nodes": ["model.vantara.customer_revenue"]},
            },
        ]
    }

    batch = capture_dbt_artifacts(
        manifest=manifest,
        run_results=run_results,
        source_authority=authority,
        manifest_evidence_ref_id=uuid4(),
        run_results_evidence_ref_id=uuid4(),
        observed_at=NOW,
        fresh_until=NOW + timedelta(hours=1),
        external_asset_ids={"source.vantara.invoices": source_asset_id},
    )

    assert {item.kind for item in batch.assets} == {
        TwinAssetKind.TRANSFORMATION,
        TwinAssetKind.TEST,
    }
    assert len(batch.relationships) == 2
    assert {item.kind for item in batch.observations} == {
        TwinObservationKind.EXECUTION_RESULT,
        TwinObservationKind.TEST_RESULT,
    }
    payload = batch.model_dump_json()
    assert "compiled_code" not in payload
    assert "select *" not in payload


def test_profile_capture_persists_aggregates_without_samples_or_top_values() -> None:
    authority = SourceAuthorityRef(
        authority_id="de006_profiler",
        contract_version="1.0",
        scope=("VANTARA_RAW",),
    )
    asset = AssetRef(
        connector_id="snowflake_ro",
        address=("VANTARA_RAW", "BILLING", "INVOICES"),
        kind=AssetKind.TABLE,
        platform_type="snowflake",
    )
    masking = MaskingState(
        pii_columns=("EMAIL",),
        samples_masked=True,
        top_values_masked=True,
    )
    profile = DatasetProfileArtifact(
        fixture_version="tiny-v1",
        asset=asset,
        profile_id=uuid4(),
        describe_snapshot_id=uuid4(),
        capability_profile_id=uuid4(),
        row_count=10,
        sampled=False,
        columns=(
            ProfileColumn(
                name="INVOICE_ID",
                null_ratio=0,
                distinct_ratio=1,
                top_values=(),
                inferred_semantic="ID",
            ),
        ),
        candidate_keys=(),
        key_evidence=(),
        duplicate_evidence=(),
        duplicate_groups_estimate=0,
        masking=masking,
        column_types=(("INVOICE_ID", "NUMBER"),),
    )
    budget = BudgetUsage(
        queries=1,
        pairs=0,
        elapsed_seconds=0.1,
        max_queries=10,
        max_pairs=10,
        max_seconds=30,
        sample_n=5,
    )
    result = ProfilingRunResult(
        fixture_version="tiny-v1",
        duration_seconds=0.1,
        profiles=(profile,),
        relationships=(),
        samples=(),
        summary=ProfilingSummary(
            fixture_version="tiny-v1",
            connector_id="snowflake_ro",
            assets=(asset,),
            facts=(),
            relationship_count=0,
            sample_asset_count=0,
            budget=budget,
            masking_applied=True,
        ),
        relationships_id=uuid4(),
        masking=masking,
    )

    observations = capture_profile_observations(
        result=result,
        asset_ids_by_locator={asset.address: uuid4()},
        source_authority=authority,
        evidence_ref_id=uuid4(),
        observed_at=NOW,
        fresh_until=NOW + timedelta(hours=1),
    )

    assert len(observations) == 1
    payload = observations[0].model_dump_json()
    assert '"samples"' not in payload
    assert '"top_values"' not in payload
    assert '"row_count":10' in payload
