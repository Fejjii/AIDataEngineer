"""Provider-neutral SQL and asset addressing contracts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AssetKind(str, Enum):
    TABLE = "TABLE"
    VIEW = "VIEW"
    SCHEMA = "SCHEMA"
    DATABASE = "DATABASE"
    FILE = "FILE"
    OTHER = "OTHER"


class AssetRef(BaseModel):
    """Provider-neutral hierarchical asset address.

    ``address`` is an ordered hierarchy. A warehouse connector interprets
    segments as ``(database, schema, object)``; a VCS connector may use
    ``(owner, repo)``. Dialects normalize identifiers before comparison.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: str = Field(min_length=1)
    address: tuple[str, ...]
    kind: AssetKind
    platform_type: str | None = None


class SqlText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dialect: str = Field(min_length=1)
    text: str
    classification: SqlClassification | None = None


class SqlClassification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_types: tuple[str, ...]
    objects_read: tuple[AssetRef, ...]
    objects_written: tuple[AssetRef, ...]
    functions: tuple[str, ...]
    table_functions: tuple[str, ...]
    stages_or_urls: tuple[str, ...]
    unsafe_constructs: tuple[str, ...]
    unknown_ast_nodes: tuple[str, ...]
    is_read_only: bool
    is_destructive: bool
    is_multi_statement: bool
    has_dynamic_sql: bool
    parse_ok: bool
    parse_error: str | None = None
    normalized_sql: str = ""
