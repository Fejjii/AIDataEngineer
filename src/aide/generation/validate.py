"""Static validation of bounded Interview MVP dbt artifacts."""

from __future__ import annotations

import re

import sqlglot
from sqlglot.errors import ParseError

from aide.capabilities.io import TransformationFile

SNOWFLAKE_TARGET_IF_RE = re.compile(
    r"\{%\s*if\s+target\.type\s*==\s*['\"]snowflake['\"]\s*%\}"
    r"(.*?)"
    r"\{%\s*else\s*%\}"
    r"(.*?)"
    r"\{%\s*endif\s*%\}",
    re.I | re.S,
)
SNOWFLAKE_IF_ENDIF_RE = re.compile(
    r"\{%\s*if\s+target\.type\s*==\s*['\"]snowflake['\"]\s*%\}"
    r"(.*?)"
    r"\{%\s*endif\s*%\}",
    re.I | re.S,
)
CONFIG_RE = re.compile(r"\{\{\s*config\s*\(.*?\)\s*\}\}", re.I | re.S)
SOURCE_RE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
    re.I,
)
REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.I)


class GeneratedSqlInvalid(ValueError):
    pass


def render_target_jinja(raw: str, *, target_type: str = "duckdb") -> str:
    """Resolve ``target.type`` branches. ``if/else/endif`` is applied before ``if/endif``."""
    snowflake = target_type.lower() == "snowflake"

    def if_else(match: re.Match[str]) -> str:
        return match.group(1) if snowflake else match.group(2)

    def if_endif(match: re.Match[str]) -> str:
        return match.group(1) if snowflake else ""

    rendered = SNOWFLAKE_TARGET_IF_RE.sub(if_else, raw)
    return SNOWFLAKE_IF_ENDIF_RE.sub(if_endif, rendered)


def strip_jinja_for_parse(raw: str) -> str:
    sql = render_target_jinja(raw, target_type="duckdb")
    sql = CONFIG_RE.sub("", sql)
    sql = SOURCE_RE.sub(lambda match: f'"src_{match.group(1)}_{match.group(2)}"', sql)
    sql = REF_RE.sub(lambda match: f'"ref_{match.group(1)}"', sql)
    sql = re.sub(r"\{%.*?%\}", "", sql)
    return sql.strip()


def validate_generated_files(files: tuple[TransformationFile, ...]) -> None:
    """Parse generated SQL after jinja stripping. Fail closed on leftover templates."""
    if not files:
        raise GeneratedSqlInvalid("generation produced no files")
    for item in files:
        if not item.path.endswith(".sql"):
            continue
        sql = strip_jinja_for_parse(item.content)
        if "{{" in sql or "{%" in sql:
            raise GeneratedSqlInvalid(f"unresolved jinja in {item.path}")
        try:
            sqlglot.parse(sql, dialect="duckdb")
        except ParseError as exc:
            raise GeneratedSqlInvalid(f"invalid SQL in {item.path}: {exc}") from exc
