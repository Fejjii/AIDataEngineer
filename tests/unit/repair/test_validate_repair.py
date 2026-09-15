from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from aide.domain.artifacts import ExecutionMode
from aide.domain.failures import FailureClass
from aide.domain.repair import (
    ACCEPTED_ARTIFACT_PATH,
    ACCEPTED_FROM_COLUMN,
    ACCEPTED_TO_COLUMN,
    DriftColumn,
    DriftEvidence,
    ProposeRepairInput,
    RepairBudgetSnapshot,
    RepairProposal,
    RepairValidation,
    ValidateRepairInput,
)
from aide.domain.sql import AssetKind, AssetRef
from aide.domain.twin import SourceAuthorityRef
from aide.repair.diff import replace_column_reference, sha256_text
from aide.repair.propose import propose_accepted_repair
from aide.repair.validate import validate_repair

ORIGINAL_SQL = """{{ config(materialized='view') }}
select
  INVOICE_ID as invoice_id,
  INVOICE_STATUS as invoice_status,
  TOTAL_AMOUNT as total_amount
from {{ source('billing', 'invoices') }}
"""

ACCEPTED_ASSET = AssetRef(
    connector_id="snowflake_ro",
    address=("VANTARA_RAW", "BILLING", "INVOICES"),
    kind=AssetKind.TABLE,
    platform_type="snowflake",
)
AUTHORITY = SourceAuthorityRef(
    authority_id="snowflake_ro", contract_version="1.0.0", scope=("VANTARA_RAW",)
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _drift(**overrides: object) -> DriftEvidence:
    evidence_id = uuid4()
    payload = {
        "observation_id": uuid4(),
        "evidence_ref_id": evidence_id,
        "asset": ACCEPTED_ASSET,
        "from_column": ACCEPTED_FROM_COLUMN,
        "to_column": ACCEPTED_TO_COLUMN,
        "old_data_type": "VARCHAR",
        "new_data_type": "VARCHAR",
        "drifted": True,
        "added": (DriftColumn(name="STATUS", data_type="VARCHAR"),),
        "removed": (DriftColumn(name="INVOICE_STATUS", data_type="VARCHAR"),),
        "observed_at": _now(),
        "fresh_until": _now() + timedelta(hours=1),
        "source_authority": AUTHORITY,
        "authoritative": True,
        "sha256": sha256_text("drift"),
        "execution_mode": ExecutionMode.MOCK,
        "twin_snapshot_id": uuid4(),
    }
    payload.update(overrides)
    return DriftEvidence(**payload)  # type: ignore[arg-type]


def _proposal(drift: DriftEvidence, **overrides: object) -> RepairProposal:
    payload = ProposeRepairInput(
        failure_class=FailureClass.SCHEMA_MISMATCH,
        asset=ACCEPTED_ASSET,
        from_column=ACCEPTED_FROM_COLUMN,
        to_column=ACCEPTED_TO_COLUMN,
        old_data_type="VARCHAR",
        new_data_type="VARCHAR",
        added=(DriftColumn(name="STATUS", data_type="VARCHAR"),),
        removed=(DriftColumn(name="INVOICE_STATUS", data_type="VARCHAR"),),
        current_columns=(DriftColumn(name="STATUS", data_type="VARCHAR"),),
        baseline_columns=(DriftColumn(name="INVOICE_STATUS", data_type="VARCHAR"),),
        artifact_path=ACCEPTED_ARTIFACT_PATH,
        artifact_sql=ORIGINAL_SQL,
        preimage_sha256=sha256_text(ORIGINAL_SQL),
        twin_snapshot_id=drift.twin_snapshot_id,
        estate_context_sha256=sha256_text("estate"),
        drift_evidence_ref_id=drift.evidence_ref_id,
        source_authority=AUTHORITY,
    )
    proposal = propose_accepted_repair(payload)
    return proposal.model_copy(update=overrides) if overrides else proposal


def _budget(**overrides: int | bool) -> RepairBudgetSnapshot:
    payload: dict[str, int | bool] = {
        "proposal_count": 1,
        "applied_count": 0,
        "post_repair_revalidation_count": 0,
    }
    payload.update(overrides)
    return RepairBudgetSnapshot.model_validate(payload)


def _input(
    *,
    drift: DriftEvidence | None = None,
    proposal: RepairProposal | None = None,
    original_sql: str = ORIGINAL_SQL,
    files: tuple[tuple[str, str, str], ...] | None = None,
    budget: RepairBudgetSnapshot | None = None,
    now: datetime | None = None,
) -> ValidateRepairInput:
    drift = drift or _drift()
    proposal = proposal or _proposal(drift)
    files = files or ((ACCEPTED_ARTIFACT_PATH, ORIGINAL_SQL, "MODEL_SQL"),)
    return ValidateRepairInput(
        proposal=proposal,
        original_sql=original_sql,
        original_files=files,
        drift=drift,
        budget=budget or _budget(),
        now=now or _now(),
        static_sql_ok=True,
    )


def _reasons(result: RepairValidation) -> set[str]:
    return set(result.reason_codes)


def test_accepted_invoice_status_repair_is_allowed() -> None:
    result = validate_repair(_input())
    assert result.allowed
    assert result.parsed_diff.column_reference_replacements == (("INVOICE_STATUS", "STATUS"),)
    assert not result.parsed_diff.broader_than_allowed
    assert not result.parsed_diff.grain_changed
    patched = replace_column_reference(ORIGINAL_SQL, "INVOICE_STATUS", "STATUS")
    assert "STATUS as invoice_status" in patched
    assert "INVOICE_STATUS" not in patched
    assert "as STATUS" not in patched


def test_wrong_table_is_rejected() -> None:
    drift = _drift(
        asset=AssetRef(
            connector_id="snowflake_ro",
            address=("VANTARA_RAW", "BILLING", "PAYMENTS"),
            kind=AssetKind.TABLE,
            platform_type="snowflake",
        )
    )
    proposal = _proposal(drift, asset=drift.asset)
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "WRONG_TABLE" in _reasons(result)


def test_wrong_source_relation_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace("invoices", "payments")
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "BROADER_PARSED_DIFF" in _reasons(result) or "WRONG_SOURCE" in _reasons(result)


def test_wrong_source_path_is_rejected() -> None:
    drift = _drift()
    proposal = _proposal(drift, artifact_path="models/staging/stg_other.sql")
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "WRONG_SOURCE" in _reasons(result)


def test_different_column_rename_is_rejected() -> None:
    drift = _drift()
    proposal = _proposal(drift, from_column="CUSTOMER_ID", to_column="CUST_ID")
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "DIFFERENT_COLUMN_RENAME" in _reasons(result)


def test_different_normalized_type_is_rejected() -> None:
    drift = _drift(old_data_type="VARCHAR", new_data_type="NUMBER")
    result = validate_repair(_input(drift=drift, proposal=_proposal(drift)))
    assert not result.allowed
    assert "DIFFERENT_NORMALIZED_TYPE" in _reasons(result)


def test_preimage_hash_mismatch_is_rejected() -> None:
    drift = _drift()
    proposal = _proposal(drift, preimage_sha256=sha256_text("other"))
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "PREIMAGE_HASH_MISMATCH" in _reasons(result)


def test_join_change_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace(
        "from {{ source('billing', 'invoices') }}",
        "from {{ source('billing', 'invoices') }} "
        "join {{ source('billing', 'customers') }} using (CUSTOMER_ID)",
    )
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "JOIN_CHANGED" in _reasons(result) or "BROADER_PARSED_DIFF" in _reasons(result)


def test_filter_change_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace(
        "from {{ source('billing', 'invoices') }}",
        "from {{ source('billing', 'invoices') }}\nwhere INVOICE_STATUS = 'open'",
    )
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "FILTER_CHANGED" in _reasons(result) or "BROADER_PARSED_DIFF" in _reasons(result)


def test_grouping_change_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace(
        "from {{ source('billing', 'invoices') }}",
        "from {{ source('billing', 'invoices') }}\n"
        "group by INVOICE_ID, INVOICE_STATUS, TOTAL_AMOUNT",
    )
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "GROUPING_CHANGED" in _reasons(result) or "BROADER_PARSED_DIFF" in _reasons(result)


def test_grain_change_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace("TOTAL_AMOUNT as total_amount", "1 as extra_grain")
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "GRAIN_CHANGED" in _reasons(result) or "BROADER_PARSED_DIFF" in _reasons(result)


def test_materialization_change_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace("materialized='view'", "materialized='table'")
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "MATERIALIZATION_CHANGED" in _reasons(result)


def test_macro_change_is_rejected() -> None:
    patched = "{% macro invoices() %}select 1{% endmacro %}\n" + ORIGINAL_SQL.replace(
        "INVOICE_STATUS", "STATUS"
    )
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "MACRO_CHANGED" in _reasons(result) or "BROADER_PARSED_DIFF" in _reasons(result)


def test_yaml_change_is_rejected() -> None:
    drift = _drift()
    yaml_sql = (
        "version: 2\nmodels:\n  - name: stg_billing__invoices\n"
        "    tests:\n      - unique:\n          column_name: invoice_id\n"
    )
    proposal = _proposal(drift, artifact_path="models/staging/schema.yml").model_copy(
        update={"patched_sql": yaml_sql, "patched_sha256": sha256_text(yaml_sql)}
    )
    original_yaml = yaml_sql.replace("unique", "not_null")
    result = validate_repair(
        _input(
            drift=drift,
            proposal=proposal,
            original_sql=original_yaml,
            files=(("models/staging/schema.yml", original_yaml, "SCHEMA_YML"),),
        )
    )
    assert not result.allowed
    assert "YAML_CHANGED" in _reasons(result) or "WRONG_SOURCE" in _reasons(result)


def test_test_weakening_is_rejected() -> None:
    original = "version: 2\nmodels:\n  - name: x\n    tests:\n      - unique\n"
    patched = (
        "version: 2\nmodels:\n  - name: x\n    tests:\n      - unique:\n"
        "          config:\n            severity: warn\n"
    )
    drift = _drift()
    proposal = _proposal(drift, artifact_path="models/schema.yml").model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(
        _input(
            drift=drift,
            proposal=proposal,
            original_sql=original,
            files=(("models/schema.yml", original, "SCHEMA_YML"),),
        )
    )
    assert not result.allowed
    assert "TEST_WEAKENED" in _reasons(result) or "YAML_CHANGED" in _reasons(result)


def test_permission_change_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(permission_changed=True)))
    assert not result.allowed
    assert "PERMISSION_CHANGED" in _reasons(result)


def test_target_change_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(target_changed=True)))
    assert not result.allowed
    assert "TARGET_CHANGED" in _reasons(result)


def test_source_data_mutation_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(source_data_mutated=True)))
    assert not result.allowed
    assert "SOURCE_DATA_MUTATED" in _reasons(result)


def test_second_repair_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(applied_count=1)))
    assert not result.allowed
    assert "SECOND_REPAIR" in _reasons(result)


def test_second_repair_per_task_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(applied_count=0, applied_count_for_task=1)))
    assert not result.allowed
    assert "SECOND_REPAIR" in _reasons(result)


def test_proposal_budget_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(proposal_count=3)))
    assert not result.allowed
    assert "BUDGET_EXCEEDED" in _reasons(result)


def test_revalidation_budget_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(post_repair_revalidation_count=1)))
    assert not result.allowed
    assert "BUDGET_EXCEEDED" in _reasons(result)


def test_recursive_repair_is_rejected() -> None:
    result = validate_repair(_input(budget=_budget(recursive_requested=True)))
    assert not result.allowed
    assert "RECURSIVE_REPAIR" in _reasons(result)


def test_missing_drift_evidence_is_rejected() -> None:
    drift = _drift()
    proposal = _proposal(drift, drift_evidence_ref_id=uuid4())
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "MISSING_DRIFT_EVIDENCE" in _reasons(result)


def test_stale_drift_evidence_is_rejected() -> None:
    drift = _drift(fresh_until=_now() - timedelta(minutes=1))
    result = validate_repair(_input(drift=drift, proposal=_proposal(drift), now=_now()))
    assert not result.allowed
    assert "STALE_DRIFT_EVIDENCE" in _reasons(result)


def test_non_authoritative_drift_is_rejected() -> None:
    drift = _drift(
        authoritative=False,
        source_authority=SourceAuthorityRef(
            authority_id="llm", contract_version="1.0.0", scope=("VANTARA_RAW",)
        ),
    )
    result = validate_repair(_input(drift=drift, proposal=_proposal(drift)))
    assert not result.allowed
    assert "NON_AUTHORITATIVE_DRIFT" in _reasons(result)


def test_broader_parsed_diff_is_rejected() -> None:
    patched = ORIGINAL_SQL.replace(
        "INVOICE_STATUS as invoice_status",
        "STATUS as invoice_status,\n  1 as extra",
    )
    drift = _drift()
    proposal = _proposal(drift).model_copy(
        update={"patched_sql": patched, "patched_sha256": sha256_text(patched)}
    )
    result = validate_repair(_input(drift=drift, proposal=proposal))
    assert not result.allowed
    assert "BROADER_PARSED_DIFF" in _reasons(result) or "GRAIN_CHANGED" in _reasons(result)
