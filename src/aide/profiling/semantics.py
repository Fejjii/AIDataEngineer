"""Type and semantic hints used when enriching capability profiles."""

from __future__ import annotations

from typing import Literal

Semantic = Literal["ID", "DATE", "AMOUNT", "CODE", "TEXT", "FLAG"]

_NUMERIC_TOKENS = ("NUMBER", "NUMERIC", "DECIMAL", "DOUBLE", "FLOAT", "INT", "BIGINT", "HUGEINT")


def is_numeric_type(data_type: str) -> bool:
    upper = data_type.upper()
    return any(token in upper for token in _NUMERIC_TOKENS)


def types_compatible(left: str, right: str) -> bool:
    left_u = left.upper()
    right_u = right.upper()
    if left_u == right_u:
        return True
    left_num = is_numeric_type(left_u)
    right_num = is_numeric_type(right_u)
    if left_num and right_num:
        return True
    if "CHAR" in left_u or "TEXT" in left_u or "STRING" in left_u or left_u == "UUID":
        return "CHAR" in right_u or "TEXT" in right_u or "STRING" in right_u or right_u == "UUID"
    return False


def infer_semantic(name: str, data_type: str) -> Semantic | None:
    upper = name.upper()
    dtype = data_type.upper()
    if upper.endswith("_ID") or upper == "ID" or upper.endswith("_KEY") or upper.endswith("KEY"):
        return "ID"
    if "DATE" in dtype or "TIMESTAMP" in dtype or upper.endswith("_TS") or upper.endswith("_AT"):
        return "DATE"
    if any(token in upper for token in ("AMOUNT", "PRICE", "COST", "QTY", "QUANTITY", "TOTAL")):
        return "AMOUNT"
    if any(token in upper for token in ("CODE", "STATUS", "TYPE", "REGION", "SEGMENT")):
        return "CODE"
    if "BOOL" in dtype or upper.startswith("IS_") or upper.startswith("HAS_"):
        return "FLAG"
    if "CHAR" in dtype or "TEXT" in dtype or "STRING" in dtype or dtype == "UUID":
        return "TEXT"
    return None


def names_related(left: str, right: str) -> bool:
    left_u = left.upper()
    right_u = right.upper()
    if left_u == right_u:
        return True
    if left_u.endswith("_ID") and left_u[: -len("_ID")] and right_u.endswith("_ID"):
        return left_u.split("_")[-2:] == right_u.split("_")[-2:]
    return left_u.replace("_", "") == right_u.replace("_", "")
