"""PII masking for profile top-values and samples. No raw PII persistence."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from aide.capabilities.io import ProfileColumn, TopValue

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d[\d\-\s()]{6,}$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NAME_HINTS = (
    "NAME",
    "EMAIL",
    "PHONE",
    "FIRST_NAME",
    "LAST_NAME",
    "FULL_NAME",
    "CONTACT",
)


def column_is_sensitive(name: str, *, pii_columns: frozenset[str] = frozenset()) -> bool:
    upper = name.upper()
    if upper in pii_columns:
        return True
    return any(hint in upper for hint in _NAME_HINTS)


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        integral = value.to_integral_value()
        if value == integral:
            return int(integral)
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def mask_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(jsonable(value))
    if _EMAIL_RE.match(text):
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}"
    if _PHONE_RE.match(text):
        digits = re.sub(r"\D", "", text)
        return f"***{digits[-2:]}" if digits else "***"
    if len(text) <= 2:
        return "*" * len(text)
    return text[0] + "***"


def mask_row(row: dict[str, Any], *, sensitive: set[str]) -> dict[str, Any]:
    masked: dict[str, Any] = {}
    for key, value in row.items():
        converted = jsonable(value)
        if key in sensitive or column_is_sensitive(key):
            masked[key] = None if converted is None else mask_value(converted)
        else:
            masked[key] = converted
    return masked


def mask_profile_columns(
    columns: tuple[ProfileColumn, ...],
    *,
    pii_columns: frozenset[str],
) -> tuple[ProfileColumn, ...]:
    masked: list[ProfileColumn] = []
    for column in columns:
        if not column_is_sensitive(column.name, pii_columns=pii_columns):
            masked.append(column)
            continue
        masked.append(
            column.model_copy(
                update={
                    "min": None,
                    "max": None,
                    "mean": None,
                    "top_values": tuple(
                        TopValue(value_masked=mask_value(item.value_masked), count=item.count)
                        for item in column.top_values
                    ),
                }
            )
        )
    return tuple(masked)


def looks_like_raw_email(value: object) -> bool:
    return isinstance(value, str) and bool(_EMAIL_RE.match(value)) and "***" not in value


def looks_like_raw_phone(value: object) -> bool:
    if not isinstance(value, str) or "***" in value or _ISO_DATE_RE.match(value):
        return False
    return bool(_PHONE_RE.match(value))
