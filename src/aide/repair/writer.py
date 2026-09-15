"""Repair writer: pure patched-file construction. No filesystem or gateway I/O.

External application must go through the governed tool gateway. This module
must not import vendor connectors or the gateway application service.
"""

from __future__ import annotations

from aide.capabilities.io import TransformationFile
from aide.domain.repair import RepairProposal


def patched_files(proposal: RepairProposal) -> tuple[TransformationFile, ...]:
    """Return only the workflow-scoped DEV SQL file that may change."""
    return (
        TransformationFile(
            path=proposal.artifact_path,
            content=proposal.patched_sql,
            kind="MODEL_SQL",
        ),
    )


__all__ = ["patched_files"]
