"""Profile, sample, and relationship SQL templates in Snowflake dialect."""

from __future__ import annotations

from collections.abc import Sequence

from aide.connectors.snowflake.dialect import assert_safe_identifier, qualify_parts


def qualified_table(address: tuple[str, ...]) -> str:
    safe = tuple(assert_safe_identifier(part) for part in address)
    if len(safe) != 3:
        raise ValueError("warehouse table address must be database.schema.table")
    return qualify_parts(safe)


def quoted_column(name: str) -> str:
    return f'"{assert_safe_identifier(name)}"'


def row_count_sql(address: tuple[str, ...]) -> str:
    return f"SELECT COUNT(*) AS ROW_COUNT FROM {qualified_table(address)}"


def column_profile_sql(address: tuple[str, ...], column: str, *, numeric: bool) -> str:
    ident = quoted_column(column)
    table = qualified_table(address)
    mean_expr = f"AVG({ident})" if numeric else "NULL"
    return (
        f"SELECT COUNT(*) AS ROW_COUNT, "
        f"SUM(IFF({ident} IS NULL, 1, 0)) AS NULL_COUNT, "
        f"COUNT(DISTINCT {ident}) AS DISTINCT_COUNT, "
        f"MIN({ident}) AS MIN_VALUE, MAX({ident}) AS MAX_VALUE, "
        f"{mean_expr} AS MEAN_VALUE "
        f"FROM {table}"
    )


def column_profile_batch_sql(address: tuple[str, ...], columns: Sequence[tuple[str, bool]]) -> str:
    """One scan with the same aggregates as per-column ``column_profile_sql``."""
    if not columns:
        raise ValueError("column_profile_batch_sql requires at least one column")
    table = qualified_table(address)
    selects = ["COUNT(*) AS ROW_COUNT"]
    for index, (name, numeric) in enumerate(columns):
        ident = quoted_column(name)
        prefix = f"C{index}"
        mean_expr = f"AVG({ident})" if numeric else "NULL"
        selects.extend(
            (
                f"SUM(IFF({ident} IS NULL, 1, 0)) AS {prefix}_NULL_COUNT",
                f"COUNT(DISTINCT {ident}) AS {prefix}_DISTINCT_COUNT",
                f"MIN({ident}) AS {prefix}_MIN_VALUE",
                f"MAX({ident}) AS {prefix}_MAX_VALUE",
                f"{mean_expr} AS {prefix}_MEAN_VALUE",
            )
        )
    return f"SELECT {', '.join(selects)} FROM {table}"


def top_values_sql(address: tuple[str, ...], column: str, *, top_k: int) -> str:
    ident = quoted_column(column)
    table = qualified_table(address)
    limit = max(1, int(top_k))
    return (
        f"SELECT {ident} AS VALUE, COUNT(*) AS VALUE_COUNT "
        f"FROM {table} "
        f"WHERE {ident} IS NOT NULL "
        f"GROUP BY {ident} "
        f"ORDER BY VALUE_COUNT DESC "
        f"LIMIT {limit}"
    )


def sample_sql(
    address: tuple[str, ...],
    columns: tuple[str, ...] | None,
    n: int,
    where_sql: str | None,
) -> str:
    table = qualified_table(address)
    projection = "*"
    if columns:
        projection = ", ".join(quoted_column(name) for name in columns)
    limit = max(1, min(int(n), 20))
    clause = f" WHERE {where_sql}" if where_sql else ""
    return f"SELECT {projection} FROM {table}{clause} LIMIT {limit}"


def inclusion_sql(
    from_address: tuple[str, ...],
    from_column: str,
    to_address: tuple[str, ...],
    to_column: str,
) -> str:
    child = qualify_parts(tuple(assert_safe_identifier(part) for part in from_address))
    parent = qualify_parts(tuple(assert_safe_identifier(part) for part in to_address))
    child_col = quoted_column(from_column)
    parent_col = quoted_column(to_column)
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


def explain_sql(sql: str) -> str:
    return f"EXPLAIN USING JSON {sql}"
