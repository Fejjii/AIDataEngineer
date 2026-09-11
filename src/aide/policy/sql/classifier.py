"""Pure SQL safety classifier. Does not execute SQL."""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from aide.domain.sql import AssetKind, AssetRef, SqlClassification, SqlText
from aide.policy.sql.constructs import (
    DESTRUCTIVE_STATEMENT_TYPES,
    SAFE_STATEMENT_TYPES,
    UNSAFE_CONSTRUCT_MARKERS,
    WRITE_STATEMENT_TYPES,
)
from aide.policy.sql.dialects import DialectId, registered_dialects
from aide.policy.sql.functions import SAFE_FUNCTIONS, SAFE_TABLE_FUNCTIONS

_STAGE_RE = re.compile(r"@(?:[\w.]+|%)|(?:s3|gcs|azure|https?)://", re.IGNORECASE)
_DYNAMIC_RE = re.compile(
    r"\bEXECUTE\s+IMMEDIATE\b|\bEXECUTE\s+IMMEDIATE\b|\bIDENTIFY\b|\bEVAL\b",
    re.IGNORECASE,
)
_SESSION_RE = re.compile(
    r"\bUSE\s+(ROLE|WAREHOUSE|DATABASE|SCHEMA|SECONDARY\s+ROLES)\b|\bALTER\s+SESSION\b",
    re.IGNORECASE,
)

SAFE_AST_TYPES: frozenset[type[exp.Expression]] = frozenset(
    {
        exp.Select,
        exp.Column,
        exp.Table,
        exp.Alias,
        exp.Literal,
        exp.Identifier,
        exp.EQ,
        exp.NEQ,
        exp.GT,
        exp.GTE,
        exp.LT,
        exp.LTE,
        exp.And,
        exp.Or,
        exp.Not,
        exp.Is,
        exp.In,
        exp.Between,
        exp.Like,
        exp.Func,
        exp.Anonymous,
        exp.Case,
        exp.Cast,
        exp.TryCast,
        exp.Window,
        exp.WindowSpec,
        exp.Ordered,
        exp.Limit,
        exp.Offset,
        exp.Join,
        exp.Union,
        exp.Intersect,
        exp.Except,
        exp.CTE,
        exp.Subquery,
        exp.Star,
        exp.Null,
        exp.Boolean,
        exp.Paren,
        exp.Distinct,
        exp.Having,
        exp.Group,
        exp.Where,
        exp.With,
        exp.Qualify,
        exp.Order,
        exp.From,
        exp.TableAlias,
        exp.Dot,
        exp.Var,
        exp.DataType,
        exp.DataTypeParam,
        exp.Neg,
        exp.Add,
        exp.Sub,
        exp.Mul,
        exp.Div,
        exp.Mod,
        exp.Coalesce,
        exp.Count,
        exp.Max,
        exp.Min,
        exp.Sum,
        exp.Avg,
        exp.Extract,
        exp.Trim,
        exp.Concat,
        exp.Lower,
        exp.Upper,
        exp.Substring,
        exp.Nullif,
        exp.If,
        exp.Explode,
        exp.Lateral,
        exp.Unnest,
        exp.Values,
        exp.Tuple,
        exp.Array,
        exp.JSONExtract,
        exp.JSONExtractScalar,
        exp.BitwiseAnd,
        exp.BitwiseOr,
        exp.Escape,
        exp.Exists,
        exp.Any,
        exp.All,
        exp.ILike,
        exp.SimilarTo,
        exp.AtTimeZone,
        exp.TsOrDsToDate,
        exp.Time,
        exp.Timestamp,
        exp.Date,
        exp.CurrentDate,
        exp.CurrentTimestamp,
        exp.Anonymous,
        exp.ColumnDef,
        exp.Schema,
        exp.PartitionedByProperty,
        exp.Property,
        exp.Literal,
    }
)


class ClassifierError(ValueError):
    pass


def classify_sql(sql: SqlText, *, connector_id: str = "unknown") -> SqlClassification:
    dialect = sql.dialect.lower()
    if dialect not in registered_dialects() and dialect not in {item.value for item in DialectId}:
        return _fail_closed(sql, f"unknown dialect {sql.dialect!r}", connector_id=connector_id)
    text = sql.text.strip()
    if not text:
        return _fail_closed(sql, "empty SQL", connector_id=connector_id)
    try:
        parsed = sqlglot.parse(text, read=dialect)
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as exc:
        return _fail_closed(sql, str(exc), connector_id=connector_id)
    statements: list[exp.Expression] = [item for item in parsed if item is not None]
    if not statements:
        return _fail_closed(sql, "no statements parsed", connector_id=connector_id)
    if not _round_trip_ok(statements, dialect):
        return _fail_closed(sql, "dialect round-trip AST mismatch", connector_id=connector_id)

    statement_types = tuple(_statement_type(item) for item in statements)
    is_multi = len(statements) > 1
    functions: list[str] = []
    table_functions: list[str] = []
    stages: list[str] = []
    unsafe: list[str] = []
    unknown_nodes: list[str] = []
    objects_read: list[AssetRef] = []
    objects_written: list[AssetRef] = []

    raw_upper = text.upper()
    if _DYNAMIC_RE.search(text) or "EXECUTE IMMEDIATE" in raw_upper:
        unsafe.append("DYNAMIC_SQL")
    if _SESSION_RE.search(text):
        unsafe.append("SESSION_MUTATION")
    for match in _STAGE_RE.findall(text):
        stages.append(match)

    for marker in UNSAFE_CONSTRUCT_MARKERS:
        if marker in raw_upper:
            unsafe.append(marker.replace(" ", "_"))

    safe_fns = SAFE_FUNCTIONS.get(dialect, frozenset())
    safe_tfs = SAFE_TABLE_FUNCTIONS.get(dialect, frozenset())

    for statement in statements:
        stmt_type = _statement_type(statement)
        resolved_tables: list[AssetRef] = []
        for table in statement.find_all(exp.Table):
            asset = _canonical_asset(table, dialect, connector_id)
            if asset is not None:
                resolved_tables.append(asset)
        if stmt_type in WRITE_STATEMENT_TYPES or stmt_type in DESTRUCTIVE_STATEMENT_TYPES:
            objects_written.extend(resolved_tables)
        else:
            objects_read.extend(resolved_tables)
        for func in statement.find_all(exp.Func, exp.Anonymous):
            name = _function_name(func)
            if not name:
                continue
            functions.append(name)
            if isinstance(func.parent, exp.From) or isinstance(func, exp.Table):
                table_functions.append(name)
                if name not in safe_tfs:
                    unsafe.append(f"UNSAFE_FUNCTION:{name}")
            elif name not in safe_fns:
                unsafe.append(f"UNSAFE_FUNCTION:{name}")
            if name.startswith("SYSTEM$") or name.startswith("EXTERNAL"):
                unsafe.append(f"UNSAFE_FUNCTION:{name}")
        for node in statement.walk():
            if not isinstance(node, exp.Expression):
                continue
            if type(node) not in SAFE_AST_TYPES and not _is_known_safe_family(node):
                unknown_nodes.append(type(node).__name__)

    unique_unsafe = tuple(sorted(set(unsafe)))
    unique_unknown = tuple(sorted(set(unknown_nodes)))
    is_destructive = any(item in DESTRUCTIVE_STATEMENT_TYPES for item in statement_types)
    has_dynamic = "DYNAMIC_SQL" in unique_unsafe
    is_read_only = (
        (not is_multi)
        and (not is_destructive)
        and (not objects_written)
        and (not unique_unsafe)
        and (not unique_unknown)
        and (not stages)
        and all(item in SAFE_STATEMENT_TYPES for item in statement_types)
    )
    if unique_unknown or unique_unsafe or stages:
        is_read_only = False
    if unique_unknown and not is_destructive:
        is_destructive = True

    normalized = "; ".join(stmt.sql(dialect=dialect) for stmt in statements)
    return SqlClassification(
        statement_types=statement_types,
        objects_read=tuple(_unique_assets(objects_read)),
        objects_written=tuple(_unique_assets(objects_written)),
        functions=tuple(sorted(set(functions))),
        table_functions=tuple(sorted(set(table_functions))),
        stages_or_urls=tuple(sorted(set(stages))),
        unsafe_constructs=unique_unsafe,
        unknown_ast_nodes=unique_unknown,
        is_read_only=is_read_only,
        is_destructive=is_destructive or (not is_read_only and bool(objects_written)),
        is_multi_statement=is_multi,
        has_dynamic_sql=has_dynamic,
        parse_ok=True,
        parse_error=None,
        normalized_sql=normalized,
    )


def _fail_closed(sql: SqlText, error: str, *, connector_id: str) -> SqlClassification:
    del connector_id
    return SqlClassification(
        statement_types=(),
        objects_read=(),
        objects_written=(),
        functions=(),
        table_functions=(),
        stages_or_urls=(),
        unsafe_constructs=("UNPARSEABLE",),
        unknown_ast_nodes=(),
        is_read_only=False,
        is_destructive=True,
        is_multi_statement=False,
        has_dynamic_sql=False,
        parse_ok=False,
        parse_error=error,
        normalized_sql="",
    )


def _round_trip_ok(statements: list[exp.Expression], dialect: str) -> bool:
    for statement in statements:
        rendered = statement.sql(dialect=dialect)
        try:
            reparsed = sqlglot.parse_one(rendered, read=dialect)
        except sqlglot.errors.ParseError:
            return False
        if reparsed is None:
            return False
        if statement.sql(dialect=dialect) != reparsed.sql(dialect=dialect):
            return False
    return True


def _statement_type(statement: exp.Expression) -> str:
    key = type(statement).__name__.upper()
    if isinstance(statement, exp.Command):
        raw = str(statement.this or statement).upper()
        for candidate in (
            "SHOW",
            "DESCRIBE",
            "DESC",
            "USE",
            "EXECUTE",
            "CALL",
            "PUT",
            "GET",
            "LIST",
            "COPY",
        ):
            if raw.startswith(candidate):
                return candidate
        return "COMMAND"
    mapping = {
        "SELECT": "SELECT",
        "UNION": "SELECT",
        "INTERSECT": "SELECT",
        "EXCEPT": "SELECT",
        "CREATE": "CREATE",
        "DROPTABLE": "DROP",
        "DROP": "DROP",
        "INSERT": "INSERT",
        "UPDATE": "UPDATE",
        "DELETE": "DELETE",
        "TRUNCATE": "TRUNCATE",
        "MERGETABLE": "MERGE",
        "MERGE": "MERGE",
        "ALTER": "ALTER",
        "GRANT": "GRANT",
        "REVOKE": "REVOKE",
        "EXPLAIN": "EXPLAIN",
        "DESCRIBE": "DESCRIBE",
        "COMMAND": "COMMAND",
    }
    return mapping.get(key, key)


def _function_name(func: exp.Expression) -> str:
    raw: Any = func.sql_name() if hasattr(func, "sql_name") else None
    if not raw:
        raw = func.name if hasattr(func, "name") else None
    if not raw and isinstance(func, exp.Anonymous):
        raw = func.this
    return str(raw).upper() if raw else ""


def _canonical_asset(table: exp.Table, dialect: str, connector_id: str) -> AssetRef | None:
    name = table.name
    if not name:
        return None
    catalog = table.catalog
    db = table.db
    parts = [
        _normalize_ident(catalog, dialect) if catalog else None,
        _normalize_ident(db, dialect) if db else None,
        _normalize_ident(name, dialect),
    ]
    address = tuple(part for part in parts if part)
    if not address:
        return None
    return AssetRef(
        connector_id=connector_id,
        address=address,
        kind=AssetKind.TABLE,
        platform_type=dialect,
    )


def _normalize_ident(value: str, dialect: str) -> str:
    text = value.strip()
    quoted = (text.startswith('"') and text.endswith('"')) or (
        text.startswith("`") and text.endswith("`")
    )
    if quoted:
        return text[1:-1]
    if dialect == "snowflake":
        return text.upper()
    return text


def _unique_assets(assets: list[AssetRef]) -> list[AssetRef]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    result: list[AssetRef] = []
    for asset in assets:
        key = (asset.connector_id, asset.address)
        if key in seen:
            continue
        seen.add(key)
        result.append(asset)
    return result


def _is_known_safe_family(node: exp.Expression) -> bool:
    name = type(node).__name__
    if name.endswith("Property") or name.endswith("Column"):
        return True
    return name in {"Identifier", "Literal", "Var", "EQ", "Alias"}
