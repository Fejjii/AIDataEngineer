"""Snowflake sqlglot dialect helpers and identifier quoting rules."""

from __future__ import annotations

import re

import sqlglot
from sqlglot import exp

from aide.connectors.snowflake.errors import SnowflakeMappedError
from aide.domain.failures import FailureClass
from aide.domain.sql import AssetKind, AssetRef

DIALECT = "snowflake"
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_READ_STATEMENT_TYPES = frozenset({"SELECT", "EXPLAIN", "SHOW", "DESCRIBE", "DESC", "WITH"})
_WRITE_STATEMENT_TYPES = frozenset(
    {"CREATE", "DROP", "INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"}
)


def normalize_identifier(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1].replace('""', '"')
    return text.upper()


def quote_identifier(value: str) -> str:
    normalized = value.replace('"', '""')
    return f'"{normalized}"'


def qualify_parts(parts: tuple[str, ...]) -> str:
    return ".".join(quote_identifier(normalize_identifier(part)) for part in parts if part)


def normalize_address(parts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(normalize_identifier(part) for part in parts)


def assert_safe_identifier(value: str) -> str:
    normalized = normalize_identifier(value)
    if not _IDENT_RE.match(normalized):
        raise SnowflakeMappedError(
            FailureClass.UNSAFE_OPERATION,
            "object identifier is not a safe Snowflake identifier",
        )
    return normalized


def parse_round_trip(sql: str) -> exp.Expression:
    try:
        tree = sqlglot.parse_one(sql, read=DIALECT)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        raise SnowflakeMappedError(FailureClass.SQL_SYNTAX, "SQL did not parse") from exc
    if tree is None:
        raise SnowflakeMappedError(FailureClass.SQL_SYNTAX, "SQL produced no AST")
    rendered = tree.sql(dialect=DIALECT)
    try:
        reparsed = sqlglot.parse_one(rendered, read=DIALECT)
    except sqlglot.errors.ParseError as exc:
        raise SnowflakeMappedError(
            FailureClass.SQL_SYNTAX, "SQL round-trip reparse failed"
        ) from exc
    if reparsed is None or tree.sql(dialect=DIALECT) != reparsed.sql(dialect=DIALECT):
        raise SnowflakeMappedError(FailureClass.SQL_SYNTAX, "SQL dialect round-trip AST mismatch")
    return tree


def statement_type(sql: str) -> str:
    tree = parse_round_trip(sql)
    if isinstance(tree, exp.Select):
        return "SELECT"
    if isinstance(tree, exp.Create):
        return "CREATE"
    if isinstance(tree, exp.Drop):
        return "DROP"
    if type(tree).__name__.upper() == "EXPLAIN":
        return "EXPLAIN"
    key = type(tree).__name__.upper()
    return {"UNION": "SELECT", "INTERSECT": "SELECT", "EXCEPT": "SELECT"}.get(key, key)


def is_read_statement(sql: str) -> bool:
    return statement_type(sql) in _READ_STATEMENT_TYPES


def is_write_statement(sql: str) -> bool:
    return statement_type(sql) in _WRITE_STATEMENT_TYPES


def referenced_tables(sql: str, *, connector_id: str) -> tuple[AssetRef, ...]:
    tree = parse_round_trip(sql)
    assets: list[AssetRef] = []
    seen: set[tuple[str, ...]] = set()
    for table in tree.find_all(exp.Table):
        parts = tuple(
            part
            for part in (
                normalize_identifier(table.catalog) if table.catalog else None,
                normalize_identifier(table.db) if table.db else None,
                normalize_identifier(table.name) if table.name else None,
            )
            if part
        )
        if not parts or parts in seen:
            continue
        seen.add(parts)
        assets.append(
            AssetRef(
                connector_id=connector_id,
                address=parts,
                kind=AssetKind.TABLE,
                platform_type=DIALECT,
            )
        )
    return tuple(assets)


def rewrite_snowflake_to_duckdb(sql: str) -> str:
    tree = parse_round_trip(sql)
    for table in tree.find_all(exp.Table):
        parts = [part for part in (table.catalog, table.db, table.name) if part]
        if not parts:
            continue
        ident = ".".join(normalize_identifier(str(part)) for part in parts)
        table.set("this", exp.to_identifier(ident, quoted=True))
        table.set("db", None)
        table.set("catalog", None)
    return tree.sql(dialect="duckdb")
