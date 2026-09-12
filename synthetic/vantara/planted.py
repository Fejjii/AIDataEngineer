"""Analysis helpers for planted Vantara data problems."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from synthetic.vantara.rng import normalize_domain


def normalized_domain_duplicate_rate(accounts: list[dict[str, Any]]) -> float:
    """Fraction of account rows that are extras in a normalized domain duplicate group."""
    if not accounts:
        return 0.0
    groups: Counter[str] = Counter()
    for row in accounts:
        domain = row.get("WEBSITE_DOMAIN")
        if domain:
            groups[normalize_domain(str(domain))] += 1
    duplicate_rows = sum(size - 1 for size in groups.values() if size > 1)
    return duplicate_rows / len(accounts)


def normalized_domain_group_count(accounts: list[dict[str, Any]]) -> int:
    groups: Counter[str] = Counter(
        normalize_domain(str(row["WEBSITE_DOMAIN"]))
        for row in accounts
        if row.get("WEBSITE_DOMAIN")
    )
    return sum(1 for size in groups.values() if size > 1)


def payment_grain_groups(
    payments: list[dict[str, Any]],
) -> dict[tuple[int, str], list[dict[str, Any]]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for row in payments:
        key = (int(row["INVOICE_ID"]), str(row["PAYMENT_REF"]))
        grouped[key].append(row)
    return grouped


def late_redelivery_duplicates(payments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return duplicate rows that share INVOICE_ID+PAYMENT_REF with an earlier _LOADED_AT."""
    duplicates: list[dict[str, Any]] = []
    for rows in payment_grain_groups(payments).values():
        if len(rows) < 2:
            continue
        ordered = sorted(rows, key=lambda row: datetime.fromisoformat(str(row["_LOADED_AT"])))
        for candidate in ordered[1:]:
            if "redelivery" in str(candidate.get("_SOURCE_FILE", "")):
                duplicates.append(candidate)
                continue
            earlier = ordered[0]
            if datetime.fromisoformat(str(candidate["_LOADED_AT"])) > datetime.fromisoformat(
                str(earlier["_LOADED_AT"])
            ):
                duplicates.append(candidate)
    return duplicates


def duplicate_payment_rate_v2(payments: list[dict[str, Any]]) -> float:
    """Rate of planted duplicate re-deliveries relative to unique payment grains."""
    groups = payment_grain_groups(payments)
    if not groups:
        return 0.0
    duplicate_grains = sum(1 for rows in groups.values() if len(rows) > 1)
    return duplicate_grains / len(groups)
