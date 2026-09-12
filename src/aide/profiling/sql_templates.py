"""Deterministic SQL templates for profiling evidence. No LLM SQL."""

from __future__ import annotations


def qualify(address: tuple[str, ...]) -> str:
    if len(address) != 3:
        raise ValueError("warehouse table address must be database.schema.table")
    return ".".join(f'"{part.upper()}"' for part in address)


def quote_column(name: str) -> str:
    cleaned = name.replace('"', "")
    if not cleaned:
        raise ValueError("column name is empty")
    return f'"{cleaned}"'


def normalized_domain_sql(address: tuple[str, ...], column: str) -> str:
    table = qualify(address)
    ident = quote_column(column)
    expr = f"REGEXP_REPLACE(LOWER(TRIM({ident})), '^www\\.', '')"
    return (
        f"SELECT COUNT(*) AS ROW_COUNT, "
        f"COUNT(DISTINCT {expr}) AS DISTINCT_NORMALIZED, "
        f"COUNT(*) - COUNT({ident}) AS NULL_COUNT "
        f"FROM {table}"
    )


def duplicate_group_sql(address: tuple[str, ...], column: str) -> str:
    table = qualify(address)
    ident = quote_column(column)
    expr = f"REGEXP_REPLACE(LOWER(TRIM({ident})), '^www\\.', '')"
    return (
        f"SELECT COUNT(*) AS GROUP_COUNT, "
        f"COALESCE(SUM(C - 1), 0) AS EXTRA_ROWS "
        f"FROM ("
        f"SELECT {expr} AS DOMAIN, COUNT(*) AS C "
        f"FROM {table} WHERE {ident} IS NOT NULL "
        f"GROUP BY 1 HAVING COUNT(*) > 1"
        f") T"
    )


def composite_uniqueness_sql(address: tuple[str, ...], columns: tuple[str, ...]) -> str:
    table = qualify(address)
    group_cols = ", ".join(quote_column(name) for name in columns)
    return (
        f"SELECT COUNT(*) AS ROW_COUNT, "
        f"(SELECT COUNT(*) FROM (SELECT {group_cols} FROM {table} GROUP BY {group_cols}) T) "
        f"AS DISTINCT_GROUPS "
        f"FROM {table}"
    )


def inclusion_sql(
    from_address: tuple[str, ...],
    from_column: str,
    to_address: tuple[str, ...],
    to_column: str,
) -> str:
    child = qualify(from_address)
    parent = qualify(to_address)
    child_col = quote_column(from_column)
    parent_col = quote_column(to_column)
    return (
        f"SELECT "
        f"(SELECT COUNT(*) FROM ("
        f"SELECT DISTINCT {child_col} FROM {child} WHERE {child_col} IS NOT NULL)) "
        f"AS CHILD_DISTINCT, "
        f"(SELECT COUNT(*) FROM ("
        f"SELECT DISTINCT {child_col} FROM {child} WHERE {child_col} IS NOT NULL "
        f"MINUS "
        f"SELECT DISTINCT {parent_col} FROM {parent}"
        f")) AS MISSING_IN_PARENT"
    )


def numeric_range_sql(address: tuple[str, ...], column: str) -> str:
    table = qualify(address)
    ident = quote_column(column)
    return (
        f"SELECT MIN({ident}) AS MIN_VALUE, MAX({ident}) AS MAX_VALUE, "
        f"AVG({ident}) AS MEAN_VALUE "
        f"FROM {table}"
    )
