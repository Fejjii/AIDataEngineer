"""Heuristic masking for samples and profile top-values. No secret values."""

from __future__ import annotations

import re
from typing import Any

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d[\d\-\s()]{6,}$")
_NAME_HINTS = ("NAME", "EMAIL", "PHONE", "FIRST_NAME", "LAST_NAME", "FULL_NAME", "CONTACT")


def column_is_sensitive(name: str) -> bool:
    upper = name.upper()
    return any(hint in upper for hint in _NAME_HINTS)


def infer_semantic(name: str, data_type: str) -> str | None:
    upper = name.upper()
    dtype = data_type.upper()
    if upper.endswith("_ID") or upper == "ID" or upper.endswith("KEY"):
        return "ID"
    if "DATE" in dtype or "TIMESTAMP" in dtype or upper.endswith("_TS") or upper.endswith("_AT"):
        return "DATE"
    if any(token in upper for token in ("AMOUNT", "PRICE", "COST", "QTY", "QUANTITY", "TOTAL")):
        return "AMOUNT"
    if any(token in upper for token in ("CODE", "STATUS", "TYPE", "REGION", "SEGMENT")):
        return "CODE"
    if "BOOL" in dtype or upper.startswith("IS_") or upper.startswith("HAS_"):
        return "FLAG"
    if "CHAR" in dtype or "TEXT" in dtype or "STRING" in dtype:
        return "TEXT"
    return None


def mask_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
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
        if key in sensitive or column_is_sensitive(key):
            masked[key] = None if value is None else mask_value(value)
        else:
            masked[key] = value
    return masked
