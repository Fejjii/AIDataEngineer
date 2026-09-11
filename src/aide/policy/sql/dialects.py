"""Extensible dialect identifiers."""

from __future__ import annotations

from enum import Enum


class DialectId(str, Enum):
    SNOWFLAKE = "snowflake"
    POSTGRES = "postgres"
    DUCKDB = "duckdb"


def registered_dialects() -> frozenset[str]:
    return frozenset(item.value for item in DialectId)


def sqlglot_dialect(dialect: str) -> str:
    if dialect not in registered_dialects() and dialect not in {item.value for item in DialectId}:
        # Unknown dialect identifiers are accepted as extension keys; fail closed later.
        return dialect
    return dialect
