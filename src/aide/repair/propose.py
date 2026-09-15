"""Propose the one allow-listed Interview MVP column-reference repair."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from aide.domain.failures import FailureClass
from aide.domain.identity import canonical_json_bytes
from aide.domain.repair import ProposeRepairInput, RepairProposal
from aide.repair.allowlist import is_accepted_mapping
from aide.repair.diff import replace_column_reference, sha256_text


def propose_accepted_repair(payload: ProposeRepairInput) -> RepairProposal:
    """Return the bounded INVOICE_STATUS → STATUS patch. Never writes artifacts."""
    hypothesis = (
        f"source column renamed {payload.from_column}→{payload.to_column} on "
        f"{'.'.join(payload.asset.address)}"
    )
    hypothesis_hash = hashlib.sha256(canonical_json_bytes({"hypothesis": hypothesis})).hexdigest()
    patched = payload.artifact_sql
    if is_accepted_mapping(payload.from_column, payload.to_column):
        patched = replace_column_reference(
            payload.artifact_sql, payload.from_column, payload.to_column
        )
    return RepairProposal(
        proposal_id=uuid4(),
        failure_class=payload.failure_class,
        asset=payload.asset,
        from_column=payload.from_column,
        to_column=payload.to_column,
        artifact_path=payload.artifact_path,
        preimage_sha256=payload.preimage_sha256,
        patched_sql=patched,
        patched_sha256=sha256_text(patched),
        hypothesis=hypothesis,
        hypothesis_hash=hypothesis_hash,
        twin_snapshot_id=payload.twin_snapshot_id,
        estate_context_sha256=payload.estate_context_sha256,
        drift_evidence_ref_id=payload.drift_evidence_ref_id,
        target_environment=payload.target_environment,
    )


def classify_execute_failure(error_classes: tuple[FailureClass | None, ...]) -> FailureClass | None:
    present = [item for item in error_classes if item is not None]
    if FailureClass.SCHEMA_MISMATCH in present:
        return FailureClass.SCHEMA_MISMATCH
    if not present:
        return None
    return present[0]


__all__ = ["classify_execute_failure", "propose_accepted_repair"]
