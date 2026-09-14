"""Deterministic safety validation for the one allowed Interview MVP repair."""

from __future__ import annotations

from aide.capabilities.io import TransformationFile
from aide.domain.repair import (
    MAX_APPLIED_REPAIRS_PER_TASK,
    MAX_APPLIED_REPAIRS_PER_WORKFLOW,
    MAX_POST_REPAIR_REVALIDATIONS,
    MAX_RECURSIVE_REPAIRS,
    MAX_REPAIR_PROPOSALS,
    RepairBlockReason,
    RepairRuleResult,
    RepairValidation,
    ValidateRepairInput,
)
from aide.generation.validate import GeneratedSqlInvalid, validate_generated_files
from aide.repair.allowlist import (
    is_accepted_asset,
    is_accepted_authority,
    is_accepted_failure,
    is_accepted_mapping,
    is_accepted_path,
    normalize_data_type,
)
from aide.repair.diff import parsed_diff, sha256_text


def validate_repair(payload: ValidateRepairInput) -> RepairValidation:
    proposal = payload.proposal
    rules: list[RepairRuleResult] = []

    def rule(rule_id: str, passed: bool, detail: str) -> None:
        rules.append(RepairRuleResult(rule_id=rule_id, passed=passed, detail=detail))

    drift = payload.drift
    rule(
        "fresh_authoritative_drift",
        bool(drift.authoritative)
        and not _stale(payload)
        and drift.evidence_ref_id == proposal.drift_evidence_ref_id,
        "fresh authoritative drift evidence must match the proposal",
    )
    if not drift.authoritative:
        rule(
            "authoritative_source",
            False,
            "drift evidence is not from an authoritative Snowflake metadata source",
        )
    else:
        rule(
            "authoritative_source",
            is_accepted_authority(drift.source_authority.authority_id),
            drift.source_authority.authority_id,
        )
    if drift.fresh_until is not None and payload.now > drift.fresh_until:
        rule("fresh_until", False, "drift evidence is stale")
    else:
        rule("fresh_until", True, "drift evidence is within freshness window")
    rule(
        "failure_class",
        is_accepted_failure(proposal.failure_class),
        proposal.failure_class.value,
    )
    rule("accepted_asset", is_accepted_asset(proposal.asset), str(proposal.asset.address))
    rule(
        "accepted_mapping",
        is_accepted_mapping(proposal.from_column, proposal.to_column),
        f"{proposal.from_column}->{proposal.to_column}",
    )
    rule(
        "equivalent_types",
        normalize_data_type(drift.old_data_type) == normalize_data_type(drift.new_data_type)
        and normalize_data_type(drift.old_data_type) != "",
        f"{drift.old_data_type}->{drift.new_data_type}",
    )
    expected_preimage = sha256_text(payload.original_sql)
    rule("sql_preimage", proposal.preimage_sha256 == expected_preimage, expected_preimage)
    patched_hash = sha256_text(proposal.patched_sql)
    rule("postimage_hash", proposal.patched_sha256 == patched_hash, patched_hash)
    rule("artifact_path", is_accepted_path(proposal.artifact_path), proposal.artifact_path)
    diff = parsed_diff(
        original_sql=payload.original_sql,
        patched_sql=proposal.patched_sql,
        original_files=payload.original_files,
        patched_path=proposal.artifact_path,
        from_column=proposal.from_column,
        to_column=proposal.to_column,
    )
    rule("join_unchanged", not diff.join_changed, "join clause")
    rule("filter_unchanged", not diff.filter_changed, "filter clause")
    rule("grouping_unchanged", not diff.grouping_changed, "grouping clause")
    rule("grain_unchanged", not diff.grain_changed, "grain/select list")
    rule("materialization_unchanged", not diff.materialization_changed, "materialization")
    rule("macro_unchanged", not diff.macro_changed, "macros")
    rule("yaml_unchanged", not diff.yaml_changed, "yaml")
    rule("tests_not_weakened", not diff.test_weakened, "tests")
    rule(
        "parsed_diff_narrow",
        not diff.broader_than_allowed,
        str(diff.column_reference_replacements),
    )
    rule(
        "permission_unchanged",
        not payload.budget.permission_changed,
        "repair must not change permissions",
    )
    rule("target_unchanged", not payload.budget.target_changed, "target remains DEV")
    rule(
        "source_data_unchanged",
        not payload.budget.source_data_mutated,
        "repair must not mutate source data",
    )
    rule(
        "proposal_budget",
        payload.budget.proposal_count <= MAX_REPAIR_PROPOSALS,
        str(payload.budget.proposal_count),
    )
    rule(
        "applied_budget",
        payload.budget.applied_count < MAX_APPLIED_REPAIRS_PER_TASK
        and payload.budget.applied_count < MAX_APPLIED_REPAIRS_PER_WORKFLOW,
        str(payload.budget.applied_count),
    )
    rule(
        "recursive_budget",
        (not payload.budget.recursive_requested) and MAX_RECURSIVE_REPAIRS == 0,
        str(payload.budget.recursive_requested),
    )
    rule(
        "revalidation_budget",
        payload.budget.post_repair_revalidation_count < MAX_POST_REPAIR_REVALIDATIONS,
        str(payload.budget.post_repair_revalidation_count),
    )
    static_ok = payload.static_sql_ok
    if static_ok:
        try:
            validate_generated_files(
                (
                    TransformationFile(
                        path=proposal.artifact_path,
                        content=proposal.patched_sql,
                        kind="MODEL_SQL",
                    ),
                )
            )
        except GeneratedSqlInvalid as exc:
            static_ok = False
            rule("static_validators", False, str(exc))
        else:
            rule("static_validators", True, "patched SQL parsed")
    else:
        rule("static_validators", False, "static validators failed before execution")
    rule(
        "original_immutable",
        expected_preimage == proposal.preimage_sha256,
        "original SQL preimage is unchanged",
    )

    reason_codes = tuple(
        _reason_for(item.rule_id) for item in rules if not item.passed and _reason_for(item.rule_id)
    )
    allowed = all(item.passed for item in rules)
    return RepairValidation(
        allowed=allowed,
        proposal_id=proposal.proposal_id,
        parsed_diff=diff,
        rules=tuple(rules),
        reason_codes=reason_codes,
        preimage_sha256=expected_preimage,
        postimage_sha256=patched_hash,
    )


def _stale(payload: ValidateRepairInput) -> bool:
    if payload.drift.fresh_until is None:
        return False
    return payload.now > payload.drift.fresh_until


def _reason_for(rule_id: str) -> str:
    mapping = {
        "fresh_authoritative_drift": RepairBlockReason.MISSING_DRIFT_EVIDENCE.value,
        "authoritative_source": RepairBlockReason.NON_AUTHORITATIVE_DRIFT.value,
        "fresh_until": RepairBlockReason.STALE_DRIFT_EVIDENCE.value,
        "failure_class": RepairBlockReason.FAILURE_CLASS_NOT_ALLOWED.value,
        "accepted_asset": RepairBlockReason.WRONG_TABLE.value,
        "accepted_mapping": RepairBlockReason.DIFFERENT_COLUMN_RENAME.value,
        "equivalent_types": RepairBlockReason.DIFFERENT_NORMALIZED_TYPE.value,
        "sql_preimage": RepairBlockReason.PREIMAGE_HASH_MISMATCH.value,
        "join_unchanged": RepairBlockReason.JOIN_CHANGED.value,
        "filter_unchanged": RepairBlockReason.FILTER_CHANGED.value,
        "grouping_unchanged": RepairBlockReason.GROUPING_CHANGED.value,
        "grain_unchanged": RepairBlockReason.GRAIN_CHANGED.value,
        "materialization_unchanged": RepairBlockReason.MATERIALIZATION_CHANGED.value,
        "macro_unchanged": RepairBlockReason.MACRO_CHANGED.value,
        "yaml_unchanged": RepairBlockReason.YAML_CHANGED.value,
        "tests_not_weakened": RepairBlockReason.TEST_WEAKENED.value,
        "parsed_diff_narrow": RepairBlockReason.BROADER_PARSED_DIFF.value,
        "permission_unchanged": RepairBlockReason.PERMISSION_CHANGED.value,
        "target_unchanged": RepairBlockReason.TARGET_CHANGED.value,
        "source_data_unchanged": RepairBlockReason.SOURCE_DATA_MUTATED.value,
        "applied_budget": RepairBlockReason.SECOND_REPAIR.value,
        "recursive_budget": RepairBlockReason.RECURSIVE_REPAIR.value,
        "proposal_budget": RepairBlockReason.BUDGET_EXCEEDED.value,
        "static_validators": RepairBlockReason.STATIC_VALIDATION_FAILED.value,
        "artifact_path": RepairBlockReason.WRONG_SOURCE.value,
    }
    return mapping.get(rule_id, "")


__all__ = ["validate_repair"]
