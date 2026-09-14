"""Interview MVP allow-list for the one automatic repair."""

from __future__ import annotations

from aide.domain.failures import FailureClass
from aide.domain.repair import (
    ACCEPTED_ARTIFACT_PATH,
    ACCEPTED_ASSET_ADDRESS,
    ACCEPTED_AUTHORITY_ID,
    ACCEPTED_FAILURE_CLASS,
    ACCEPTED_FROM_COLUMN,
    ACCEPTED_TO_COLUMN,
)
from aide.domain.sql import AssetRef

TYPE_ALIASES = {
    "TEXT": "VARCHAR",
    "STRING": "VARCHAR",
    "NVARCHAR": "VARCHAR",
    "CHAR": "VARCHAR",
    "INT": "NUMBER",
    "INTEGER": "NUMBER",
    "BIGINT": "NUMBER",
    "SMALLINT": "NUMBER",
    "DECIMAL": "NUMBER",
    "NUMERIC": "NUMBER",
    "DOUBLE": "FLOAT",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "TIMESTAMP_NTZ": "TIMESTAMP",
    "TIMESTAMP_LTZ": "TIMESTAMP",
    "TIMESTAMP_TZ": "TIMESTAMP",
    "DATETIME": "TIMESTAMP",
}


def normalize_data_type(value: str) -> str:
    text = value.strip().upper().split("(", 1)[0].strip()
    return TYPE_ALIASES.get(text, text)


def is_accepted_asset(asset: AssetRef) -> bool:
    address = tuple(part.upper() for part in asset.address[:3])
    return address == ACCEPTED_ASSET_ADDRESS


def is_accepted_mapping(from_column: str, to_column: str) -> bool:
    return (
        from_column.strip().upper() == ACCEPTED_FROM_COLUMN
        and to_column.strip().upper() == ACCEPTED_TO_COLUMN
    )


def is_accepted_failure(failure: FailureClass) -> bool:
    return failure is ACCEPTED_FAILURE_CLASS


def is_accepted_path(path: str) -> bool:
    return path.replace("\\", "/") == ACCEPTED_ARTIFACT_PATH


def is_accepted_authority(authority_id: str) -> bool:
    return authority_id == ACCEPTED_AUTHORITY_ID


__all__ = [
    "is_accepted_asset",
    "is_accepted_authority",
    "is_accepted_failure",
    "is_accepted_mapping",
    "is_accepted_path",
    "normalize_data_type",
]
