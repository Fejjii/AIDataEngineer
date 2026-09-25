"""Independent customer-revenue expectations from synthetic CSV fixtures.

This module does not read generated mart SQL. Expectations follow the
BUSINESS_CORRECTNESS_001 contract: canonical currency codes, no FX conversion,
daily grain ``customer_sk × date_day × currency``, deduplicated payments,
refunds, and deleted-CRM exclusion.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from synthetic.vantara.config import PACKAGE_ROOT

UNKNOWN_CUSTOMER_SK = hashlib.md5(b"-1").hexdigest()
_CANONICAL_CURRENCY = {"€": "EUR", "EUR": "EUR", "USD": "USD", "GBP": "GBP"}


@dataclass(frozen=True, slots=True)
class MartRow:
    customer_sk: str
    date_day: str
    currency: str
    invoiced_amount: Decimal
    paid_amount: Decimal
    refunded_amount: Decimal
    net_paid_amount: Decimal


@dataclass(frozen=True, slots=True)
class CurrencyTotal:
    currency: str
    invoiced_amount: Decimal
    paid_amount: Decimal
    refunded_amount: Decimal
    net_paid_amount: Decimal


@dataclass(frozen=True, slots=True)
class BusinessExpectation:
    fixture_version: str
    mart_rows: tuple[MartRow, ...]
    currency_totals: tuple[CurrencyTotal, ...]
    payment_source_rows: int
    payment_survivor_rows: int
    dropped_duplicate_payments: int
    refund_rows: int
    refunds_on_dropped_payments: int
    deleted_account_ids: tuple[str, ...]
    surviving_account_ids: tuple[str, ...]
    deleted_accounts_in_survivors: tuple[str, ...]
    unknown_customer_sk: str
    unknown_invoice_count: int
    unresolved_customer_ids: tuple[str, ...]


def fixture_csv_root(version: str) -> Path:
    if version not in {"v1", "v2"}:
        raise ValueError("fixture version must be v1 or v2")
    return PACKAGE_ROOT / "fixtures" / "tiny" / version / "csv"


def normalize_currency(raw: str) -> str:
    """Map source currency text to a canonical code. No FX conversion."""
    token = raw.strip().upper()
    return _CANONICAL_CURRENCY.get(token, token)


def normalize_website(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if text.startswith("www."):
        return text[4:]
    return text


def customer_sk_for(customer_id: str, known_customer_ids: set[str]) -> str:
    if customer_id in known_customer_ids:
        return hashlib.md5(customer_id.encode()).hexdigest()
    return UNKNOWN_CUSTOMER_SK


def expect_business_correctness(version: str) -> BusinessExpectation:
    root = fixture_csv_root(version)
    customers = _read_csv(root / "billing" / "customers.csv")
    invoices = _read_csv(root / "billing" / "invoices.csv")
    lines = _read_csv(root / "billing" / "invoice_lines.csv")
    payments = _read_csv(root / "payments" / "payments.csv")
    refunds = _read_csv(root / "payments" / "refunds.csv")
    accounts = _read_csv(root / "crm" / "accounts.csv")

    known_ids = {row["CUSTOMER_ID"] for row in customers}
    invoice_by_id = {row["INVOICE_ID"]: row for row in invoices}
    unresolved = tuple(
        sorted({row["CUSTOMER_ID"] for row in invoices if row["CUSTOMER_ID"] not in known_ids})
    )
    unknown_invoices = sum(1 for row in invoices if row["CUSTOMER_ID"] not in known_ids)

    survivors, dropped_ids = _surviving_payments(payments)
    payment_by_id = {row["PAYMENT_ID"]: row for row in payments}
    refunds_on_dropped = sum(1 for row in refunds if row["PAYMENT_ID"] in dropped_ids)

    measures: dict[tuple[str, str, str], list[Decimal]] = {}

    def bucket(customer_id: str, day: str, currency: str) -> list[Decimal]:
        key = (customer_sk_for(customer_id, known_ids), day, currency)
        return measures.setdefault(key, [Decimal("0"), Decimal("0"), Decimal("0")])

    for line in lines:
        invoice = invoice_by_id[line["INVOICE_ID"]]
        amounts = bucket(
            invoice["CUSTOMER_ID"],
            invoice["ISSUE_DATE"],
            normalize_currency(invoice["CURRENCY"]),
        )
        amounts[0] += Decimal(line["AMOUNT"])

    for payment in survivors:
        invoice = invoice_by_id[payment["INVOICE_ID"]]
        amounts = bucket(
            invoice["CUSTOMER_ID"],
            _utc_day(payment["PAID_AT"]),
            normalize_currency(invoice["CURRENCY"]),
        )
        amounts[1] += Decimal(payment["AMOUNT"])

    for refund in refunds:
        payment = payment_by_id[refund["PAYMENT_ID"]]
        invoice = invoice_by_id[payment["INVOICE_ID"]]
        amounts = bucket(
            invoice["CUSTOMER_ID"],
            _utc_day(refund["REFUNDED_AT"]),
            normalize_currency(invoice["CURRENCY"]),
        )
        amounts[2] += Decimal(refund["AMOUNT"])

    mart_rows = tuple(
        MartRow(
            customer_sk=customer,
            date_day=day,
            currency=currency,
            invoiced_amount=amounts[0],
            paid_amount=amounts[1],
            refunded_amount=amounts[2],
            net_paid_amount=amounts[1] - amounts[2],
        )
        for (customer, day, currency), amounts in sorted(measures.items())
    )
    by_currency: dict[str, list[Decimal]] = {}
    for row in mart_rows:
        slot = by_currency.setdefault(
            row.currency, [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")]
        )
        slot[0] += row.invoiced_amount
        slot[1] += row.paid_amount
        slot[2] += row.refunded_amount
        slot[3] += row.net_paid_amount
    currency_totals = tuple(
        CurrencyTotal(
            currency,
            amounts[0],
            amounts[1],
            amounts[2],
            amounts[3],
        )
        for currency, amounts in sorted(by_currency.items())
    )
    deleted_ids, surviving_ids = _crm_survivors(accounts)
    return BusinessExpectation(
        fixture_version=version,
        mart_rows=mart_rows,
        currency_totals=currency_totals,
        payment_source_rows=len(payments),
        payment_survivor_rows=len(survivors),
        dropped_duplicate_payments=len(payments) - len(survivors),
        refund_rows=len(refunds),
        refunds_on_dropped_payments=refunds_on_dropped,
        deleted_account_ids=deleted_ids,
        surviving_account_ids=surviving_ids,
        deleted_accounts_in_survivors=tuple(
            account_id for account_id in deleted_ids if account_id in set(surviving_ids)
        ),
        unknown_customer_sk=UNKNOWN_CUSTOMER_SK,
        unknown_invoice_count=unknown_invoices,
        unresolved_customer_ids=unresolved,
    )


def _crm_survivors(accounts: list[dict[str, str]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Latest non-deleted account per normalized website. Deleted rows never survive."""
    grouped: dict[str, list[dict[str, str]]] = {}
    deleted_ids: list[str] = []
    for row in accounts:
        if row["IS_DELETED"].strip().lower() == "true":
            deleted_ids.append(row["ACCOUNT_ID"])
            continue
        grouped.setdefault(normalize_website(row["WEBSITE_DOMAIN"]), []).append(row)
    surviving: list[str] = []
    for rows in grouped.values():
        latest_at = max(_parsed_at(item["UPDATED_AT"]) for item in rows)
        candidates = [item for item in rows if _parsed_at(item["UPDATED_AT"]) == latest_at]
        surviving.append(sorted(candidates, key=lambda item: item["ACCOUNT_ID"])[0]["ACCOUNT_ID"])
    return tuple(sorted(deleted_ids)), tuple(sorted(surviving))


def _surviving_payments(
    payments: list[dict[str, str]],
) -> tuple[list[dict[str, str]], set[str]]:
    """Keep one row per invoice_id + payment_ref: latest _LOADED_AT, then lowest payment_id."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in payments:
        grouped.setdefault((row["INVOICE_ID"], row["PAYMENT_REF"]), []).append(row)
    survivors: list[dict[str, str]] = []
    dropped: set[str] = set()
    for rows in grouped.values():
        latest_at = max(_parsed_at(item["_LOADED_AT"]) for item in rows)
        candidates = [item for item in rows if _parsed_at(item["_LOADED_AT"]) == latest_at]
        chosen = sorted(candidates, key=lambda item: int(item["PAYMENT_ID"]))[0]
        survivors.append(chosen)
        dropped.update(
            item["PAYMENT_ID"] for item in rows if item["PAYMENT_ID"] != chosen["PAYMENT_ID"]
        )
    return survivors, dropped


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _utc_day(raw: str) -> str:
    parsed = _parsed_at(raw)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC)
    return parsed.date().isoformat()


def _parsed_at(raw: str) -> datetime:
    return datetime.fromisoformat(raw)
