"""Repair package: bounded schema-drift reference correction.

This package must not import vendor connectors or the Governed Tool Gateway.
External effects are dispatched by Supervisor through the gateway.
"""

from aide.repair.allowlist import (
    is_accepted_asset,
    is_accepted_failure,
    is_accepted_mapping,
    normalize_data_type,
)
from aide.repair.diff import parsed_diff, replace_column_reference, sha256_text
from aide.repair.propose import classify_execute_failure, propose_accepted_repair
from aide.repair.validate import validate_repair
from aide.repair.writer import patched_files

__all__ = [
    "classify_execute_failure",
    "is_accepted_asset",
    "is_accepted_failure",
    "is_accepted_mapping",
    "normalize_data_type",
    "parsed_diff",
    "patched_files",
    "propose_accepted_repair",
    "replace_column_reference",
    "sha256_text",
    "validate_repair",
]
