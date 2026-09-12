"""Reconcile dbt invocations from deterministic journal and artifact evidence."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.dbt.journal import DispatchStatus, InvocationJournalEntry
from aide.connectors.dbt.workspace import file_sha256


def reconcile_create_transformation(
    *,
    expected_hashes: Mapping[str, str],
    project_root: Path,
) -> EffectFound | NoEffect | Unknown:
    if not expected_hashes:
        return Unknown(reason="create_transformation locator has no expected hashes")
    missing: list[str] = []
    mismatched: list[str] = []
    found: dict[str, str] = {}
    for relative, expected in expected_hashes.items():
        path = project_root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        actual = file_sha256(path)
        if actual != expected:
            mismatched.append(relative)
        else:
            found[relative] = actual
    if missing and len(missing) == len(expected_hashes):
        return NoEffect(evidence="authoritative absence of written transformation files")
    if missing or mismatched:
        return Unknown(
            reason="create_transformation file hashes incomplete or mismatched",
            evidence=f"missing={missing} mismatched={mismatched}",
        )
    return EffectFound(
        output={"written": [{"path": path, "sha256": digest} for path, digest in found.items()]},
        external_ref="create_transformation",
    )


def reconcile_invocation(
    *,
    journal: InvocationJournalEntry | None,
    run_results: dict[str, Any] | None,
    manifest_present: bool,
    required_nodes: tuple[str, ...],
    in_progress: bool = False,
) -> EffectFound | NoEffect | InProgress | Unknown:
    dispatched = journal is not None and journal.dispatch_status is DispatchStatus.IN_PROGRESS
    if in_progress or dispatched:
        return InProgress(
            external_ref=str(journal.attempt_id) if journal is not None else "in-progress",
            retry_after_seconds=5,
        )
    if journal is None and run_results is None and not manifest_present:
        return NoEffect(evidence="no invocation journal or dbt artifacts")
    if journal is None:
        return Unknown(reason="artifacts present without invocation journal")
    if journal.dispatch_status is DispatchStatus.NOT_DISPATCHED:
        return NoEffect(evidence="journal records no dispatch")
    if journal.dispatch_status is DispatchStatus.TIMEOUT:
        return Unknown(
            reason="invocation timed out; outcome is ambiguous",
            evidence=journal.dispatch_status.value,
        )
    if journal.dispatch_status is DispatchStatus.TERMINATED:
        return Unknown(
            reason="process terminated; never infer success from missing evidence",
            evidence=journal.dispatch_status.value,
        )
    if journal.dispatch_status is DispatchStatus.DISPATCHED and run_results is None:
        return Unknown(reason="dispatched without run_results; indeterminate")
    if run_results is None:
        compiled_ok = (
            journal.operation == "compile_transformation"
            and manifest_present
            and journal.effect_applied
        )
        if compiled_ok:
            return EffectFound(
                output={"ok": True, "manifest": True, "artifact_hashes": journal.artifact_hashes},
                external_ref=str(journal.attempt_id),
            )
        if journal.operation == "compile_transformation" and not manifest_present:
            if journal.dispatch_status is DispatchStatus.FAILED:
                return EffectFound(
                    output={
                        "ok": False,
                        "errors": ["compile failed"],
                        "artifact_hashes": journal.artifact_hashes,
                    },
                    external_ref=str(journal.attempt_id),
                )
            return Unknown(reason="compile artifacts incomplete")
        return Unknown(reason="required run_results.json is missing")
    results = run_results.get("results")
    if not isinstance(results, list):
        return Unknown(reason="run_results.json is not a valid results document")
    by_id = {
        str(item.get("unique_id")): item
        for item in results
        if isinstance(item, dict) and item.get("unique_id")
    }
    if required_nodes:
        missing_nodes = [node for node in required_nodes if not _result_covers_node(node, by_id)]
        if missing_nodes:
            return Unknown(
                reason="run_results missing required nodes",
                evidence=",".join(missing_nodes),
            )
        running = [
            node
            for node, item in by_id.items()
            if _selector_matches(node, required_nodes)
            and str(item.get("status", "")).lower() in {"running", "started"}
        ]
        if running:
            return InProgress(external_ref=str(journal.attempt_id), retry_after_seconds=5)
    statuses = [str(item.get("status", "")).lower() for item in by_id.values()]
    if any(status in {"running", "started"} for status in statuses):
        return InProgress(external_ref=str(journal.attempt_id), retry_after_seconds=5)
    output = {
        "ok": all(status in {"success", "pass", "skipped", "warn"} for status in statuses),
        "results": results,
        "artifact_hashes": journal.artifact_hashes,
        "effect_semantics": journal.effect_semantics.value,
    }
    return EffectFound(output=output, external_ref=str(journal.attempt_id))


def _selector_matches(unique_id: str, selectors: tuple[str, ...]) -> bool:
    return any(_node_matches(selector, unique_id, {}) for selector in selectors)


def _result_covers_node(selector: str, by_id: dict[str, Any]) -> bool:
    if selector in by_id:
        return True
    return any(_node_matches(selector, unique_id, item) for unique_id, item in by_id.items())


def _node_matches(selector: str, unique_id: str, item: dict[str, Any]) -> bool:
    if selector == unique_id:
        return True
    if unique_id.endswith(f".{selector}"):
        return True
    name = item.get("name")
    return isinstance(name, str) and name == selector
