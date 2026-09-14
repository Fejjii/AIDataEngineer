"""Parsed dbt SQL diff for the bounded Interview MVP repair."""

from __future__ import annotations

import hashlib
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from aide.domain.repair import ACCEPTED_ARTIFACT_PATH, ParsedArtifactDiff
from aide.generation.validate import strip_jinja_for_parse

CONFIG_RE = re.compile(r"\{\{\s*config\s*\((.*?)\)\s*\}\}", re.I | re.S)
MATERIALIZATION_RE = re.compile(r"materialized\s*=\s*['\"]([^'\"]+)['\"]", re.I)
MACRO_RE = re.compile(r"\{%\s*(macro|from|import)\b", re.I)
YAML_TEST_RE = re.compile(
    r"tests:\n(?:[ \t]+-\s+[^\n]+\n)+",
    re.I,
)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def replace_column_reference(sql: str, from_column: str, to_column: str) -> str:
    """Replace the exact source-column identifier. Leave aliases unchanged.

    Case-sensitive on purpose: ``INVOICE_STATUS as invoice_status`` must become
    ``STATUS as invoice_status``, not ``STATUS as STATUS``.
    """
    return _word_replace(sql, from_column, to_column)


def _word_replace(sql: str, from_column: str, to_column: str) -> str:
    return re.sub(rf"\b{re.escape(from_column)}\b", to_column, sql)


def parsed_diff(
    *,
    original_sql: str,
    patched_sql: str,
    original_files: tuple[tuple[str, str, str], ...],
    patched_path: str,
    from_column: str,
    to_column: str,
) -> ParsedArtifactDiff:
    """Compare original vs patched SQL and sibling artifacts.

    ``original_files`` is ``(path, content, kind)``.
    """
    replacements = _column_replacements(original_sql, patched_sql)
    expected = ((from_column.upper(), to_column.upper()),)
    expected_rewrite = replace_column_reference(original_sql, from_column, to_column)
    other_sql_changed = _canonical(patched_sql) != _canonical(expected_rewrite)
    if replacements != expected:
        other_sql_changed = True
    join_changed = _join_signature(original_sql) != _join_signature(patched_sql)
    filter_changed = _where_signature(original_sql) != _where_signature(patched_sql)
    grouping_changed = _group_signature(original_sql) != _group_signature(patched_sql)
    grain_changed = grouping_changed or _select_names(original_sql) != _select_names(patched_sql)
    materialization_changed = _materialization(original_sql) != _materialization(patched_sql)
    macro_changed = bool(MACRO_RE.search(patched_sql)) and (
        MACRO_RE.findall(original_sql) != MACRO_RE.findall(patched_sql)
    )
    yaml_changed = False
    test_weakened = False
    files_changed: list[str] = []
    by_path = {path: (content, kind) for path, content, kind in original_files}
    original_file = by_path.get(patched_path)
    if original_file is None or original_file[0] != original_sql or original_sql != patched_sql:
        files_changed.append(patched_path)
    for path, content, kind in original_files:
        if path == patched_path:
            continue
        if kind in {"SCHEMA_YML", "SOURCE_YML"} or path.endswith((".yml", ".yaml")):
            if path == patched_path:
                yaml_changed = True
            continue
        if "{{" in content and "macro" in content.lower() and path != patched_path:
            continue
    extra_yaml = [
        path
        for path, _content, kind in original_files
        if path != patched_path
        and (kind in {"SCHEMA_YML", "SOURCE_YML"} or path.endswith((".yml", ".yaml")))
    ]
    del extra_yaml
    if patched_path.endswith((".yml", ".yaml")):
        yaml_changed = True
        test_weakened = _tests_weakened(original_sql, patched_sql)
    path_unaccepted = patched_path.replace("\\", "/") != ACCEPTED_ARTIFACT_PATH
    broader = bool(
        other_sql_changed
        or join_changed
        or filter_changed
        or grouping_changed
        or grain_changed
        or materialization_changed
        or macro_changed
        or yaml_changed
        or test_weakened
        or replacements != expected
        or path_unaccepted
        or (files_changed and files_changed != [patched_path])
    )
    return ParsedArtifactDiff(
        path=patched_path,
        column_reference_replacements=replacements,
        join_changed=join_changed,
        filter_changed=filter_changed,
        grouping_changed=grouping_changed,
        grain_changed=grain_changed,
        materialization_changed=materialization_changed,
        macro_changed=macro_changed,
        yaml_changed=yaml_changed,
        test_weakened=test_weakened,
        other_sql_changed=other_sql_changed,
        files_changed=tuple(files_changed),
        broader_than_allowed=broader,
    )


def _column_replacements(original_sql: str, patched_sql: str) -> tuple[tuple[str, str], ...]:
    original_cols = _column_names(original_sql)
    patched_cols = _column_names(patched_sql)
    removed = [name for name in original_cols if name not in patched_cols]
    added = [name for name in patched_cols if name not in original_cols]
    if len(removed) == 1 and len(added) == 1:
        return ((removed[0], added[0]),)
    if original_sql == patched_sql:
        return ()
    token_pairs: list[tuple[str, str]] = []
    orig_tokens = _ident_tokens(original_sql)
    new_tokens = _ident_tokens(patched_sql)
    if len(orig_tokens) == len(new_tokens):
        for left, right in zip(orig_tokens, new_tokens, strict=True):
            if left != right:
                token_pairs.append((left, right))
        return tuple(token_pairs)
    return tuple((item, "?") for item in removed) + tuple(("?", item) for item in added)


def _ident_tokens(sql: str) -> tuple[str, ...]:
    return tuple(token.upper() for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", sql))


def _column_names(sql: str) -> tuple[str, ...]:
    tree = _parse(sql)
    if tree is None:
        return ()
    names: list[str] = []
    for column in tree.find_all(exp.Column):
        names.append(column.name.upper())
    return tuple(names)


def _join_signature(sql: str) -> tuple[str, ...]:
    tree = _parse(sql)
    if tree is None:
        return ()
    return tuple(sorted(node.sql(dialect="duckdb") for node in tree.find_all(exp.Join)))


def _where_signature(sql: str) -> str:
    tree = _parse(sql)
    if tree is None:
        return ""
    node = tree.find(exp.Where)
    return node.sql(dialect="duckdb") if node is not None else ""


def _group_signature(sql: str) -> str:
    tree = _parse(sql)
    if tree is None:
        return ""
    node = tree.find(exp.Group)
    return node.sql(dialect="duckdb") if node is not None else ""


def _select_names(sql: str) -> tuple[str, ...]:
    tree = _parse(sql)
    if tree is None:
        return ()
    select = tree.find(exp.Select)
    if select is None:
        return ()
    names: list[str] = []
    for item in select.expressions:
        alias = item.alias_or_name
        if alias:
            names.append(str(alias).upper())
    return tuple(names)


def _materialization(sql: str) -> str:
    match = CONFIG_RE.search(sql)
    if match is None:
        return ""
    inner = match.group(1)
    found = MATERIALIZATION_RE.search(inner)
    return found.group(1).lower() if found else inner.strip()


def _tests_weakened(original: str, patched: str) -> bool:
    original_tests = YAML_TEST_RE.findall(original)
    patched_tests = YAML_TEST_RE.findall(patched)
    if len(patched_tests) < len(original_tests):
        return True
    return "warn" in patched.lower() and "warn" not in original.lower()


def _parse(sql: str) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(strip_jinja_for_parse(sql), dialect="duckdb")
    except ParseError:
        return None


def _canonical(sql: str) -> str:
    tree = _parse(sql)
    if tree is None:
        return strip_jinja_for_parse(sql)
    return tree.sql(dialect="duckdb")


__all__ = ["parsed_diff", "replace_column_reference", "sha256_text"]
