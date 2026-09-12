"""Deterministic row generation for all Vantara domains."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from synthetic.vantara.config import (
    BAD_EXTRACT_DATE,
    CROSSWALK_MISSING_RATE,
    CURRENCY_VARIANT_RATE,
    DRIFT_EFFECTIVE_DATE,
    DUPLICATE_ACCOUNT_RATE,
    DUPLICATE_PAYMENT_RATE,
    NULL_CRM_ACCOUNT_ID_RATE,
    NULL_DUE_DATE_RATE,
    ORPHAN_CONTACT_RATE,
    STATUS_CASE_INCONSISTENCY_RATE,
    UNKNOWN_INVOICE_CUSTOMER_RATE,
    ProfileConfig,
)
from synthetic.vantara.planted import normalized_domain_duplicate_rate
from synthetic.vantara.rng import (
    deterministic_uuid,
    domain_surface_variant,
    fake_company_name,
    fake_domain,
    fake_email,
    fake_phone,
    normalize_domain,
    pick,
    pick_weighted,
    random_date,
    random_datetime,
    seeded_rng,
)

INDUSTRIES = ("Software", "Finance", "Healthcare", "Retail", "Manufacturing")
COUNTRIES = ("Germany", "United States", "United Kingdom", "France", "Netherlands")
ISO_COUNTRIES = ("DE", "US", "GB", "FR", "NL")
CURRENCIES = ("EUR", "USD", "GBP")
CURRENCY_VARIANTS = ("EUR", "eur", "€", "USD", "GBP")
STATUS_VARIANTS = ("active", "paused", "cancelled", "ACTIVE", "Cancelled")
INVOICE_STATUSES = ("draft", "open", "paid", "void", "uncollectible")
STAGES = ("prospect", "qualified", "proposal", "negotiation", "closed_won", "closed_lost")
PLAN_CODES = ("Starter", "Pro", "Professional", "Enterprise", "Team")


@dataclass
class GeneratedDataset:
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    metrics: dict[str, float | int | str] = field(default_factory=dict)


def _metadata(rng: Any, extract_date: date, source_file: str) -> dict[str, Any]:
    loaded = datetime(
        extract_date.year,
        extract_date.month,
        extract_date.day,
        6,
        0,
        0,
        tzinfo=UTC,
    )
    return {
        "_LOADED_AT": loaded.isoformat(),
        "_EXTRACT_DATE": extract_date.isoformat(),
        "_SOURCE_FILE": source_file,
    }


def generate_dataset(config: ProfileConfig) -> GeneratedDataset:
    rng = seeded_rng(config.seed)
    volumes = config.table_volumes
    dataset = GeneratedDataset()
    start = date(2023, 1, 1)
    end = date(2026, 8, 31)
    extract_date = date.fromisoformat(DRIFT_EFFECTIVE_DATE)

    # --- Product plans (reference, invariant count) ---
    plans: list[dict[str, Any]] = []
    for idx, code in enumerate(PLAN_CODES):
        for version in range(2):
            valid_from = date(2023 + version, 1, 1)
            valid_to = None if version == 1 else date(2024, 12, 31)
            name = "Professional" if code == "Pro" and version == 1 else code
            plans.append(
                {
                    "PLAN_CODE": code if version == 0 else "Professional",
                    "PLAN_NAME": name,
                    "VALID_FROM": valid_from.isoformat(),
                    "VALID_TO": valid_to.isoformat() if valid_to else None,
                    "MONTHLY_PRICE": round(49.0 + idx * 25 + version * 10, 2),
                    **_metadata(rng, extract_date, f"product/plans_{extract_date}.csv"),
                }
            )
    while len(plans) < volumes["product.plans"]:
        idx = len(plans)
        plans.append(
            {
                "PLAN_CODE": f"Legacy_{idx}",
                "PLAN_NAME": f"Legacy Plan {idx}",
                "VALID_FROM": random_date(rng, start, end).isoformat(),
                "VALID_TO": None,
                "MONTHLY_PRICE": round(rng.uniform(10, 500), 2),
                **_metadata(rng, extract_date, f"product/plans_{extract_date}.csv"),
            }
        )
    dataset.tables["product.plans"] = plans[: volumes["product.plans"]]

    # --- CRM accounts with duplicate domain groups (P1) ---
    account_count = volumes["crm.accounts"]
    duplicate_target = max(1, round(account_count * DUPLICATE_ACCOUNT_RATE))
    canonical_count = account_count - duplicate_target
    accounts: list[dict[str, Any]] = []
    domain_groups: list[str] = []

    for idx in range(canonical_count):
        company = fake_company_name(rng, idx)
        domain = fake_domain(rng, company, idx)
        domain_groups.append(normalize_domain(domain))
        owner_id = deterministic_uuid(f"owner:{idx}")
        created = random_datetime(rng, start, end)
        updated = created
        accounts.append(
            {
                "ACCOUNT_ID": deterministic_uuid(f"account:{idx}"),
                "ACCOUNT_NAME": company,
                "WEBSITE_DOMAIN": domain,
                "INDUSTRY": pick(rng, INDUSTRIES),
                "COUNTRY": pick(rng, COUNTRIES),
                "OWNER_ID": owner_id,
                "CREATED_AT": created.isoformat(),
                "UPDATED_AT": updated.isoformat(),
                "IS_DELETED": False,
                **_metadata(rng, extract_date, f"crm/accounts_{extract_date}.csv"),
            }
        )

    for dup_idx in range(duplicate_target):
        canonical_domain = domain_groups[dup_idx % len(domain_groups)]
        suffix = pick(rng, (" Inc", " Ltd", " LLC", " GmbH"))
        canonical_account = accounts[dup_idx % canonical_count]
        created = random_datetime(rng, start, end)
        accounts.append(
            {
                "ACCOUNT_ID": deterministic_uuid(f"account-dup:{dup_idx}"),
                "ACCOUNT_NAME": f"{canonical_account['ACCOUNT_NAME']}{suffix}",
                "WEBSITE_DOMAIN": domain_surface_variant(rng, canonical_domain, dup_idx),
                "INDUSTRY": pick(rng, INDUSTRIES),
                "COUNTRY": canonical_account["COUNTRY"],
                "OWNER_ID": deterministic_uuid(f"owner-dup:{dup_idx}"),
                "CREATED_AT": created.isoformat(),
                "UPDATED_AT": created.isoformat(),
                "IS_DELETED": dup_idx % 5 == 0,
                **_metadata(rng, extract_date, f"crm/accounts_{extract_date}.csv"),
            }
        )
    dataset.tables["crm.accounts"] = accounts

    dataset.metrics["duplicate_account_rows"] = duplicate_target
    dataset.metrics["normalized_domain_duplicate_rate"] = normalized_domain_duplicate_rate(accounts)

    # --- Billing customers (P2 null CRM_ACCOUNT_ID) ---
    customer_count = volumes["billing.customers"]
    customers: list[dict[str, Any]] = []
    for idx in range(customer_count):
        crm_account_id = None
        if rng.random() >= NULL_CRM_ACCOUNT_ID_RATE and idx < len(accounts):
            crm_account_id = accounts[idx % len(accounts)]["ACCOUNT_ID"]
        created = random_datetime(rng, start, end)
        customers.append(
            {
                "CUSTOMER_ID": idx + 1,
                "CUSTOMER_NAME": accounts[idx % len(accounts)]["ACCOUNT_NAME"]
                if idx < len(accounts)
                else fake_company_name(rng, idx),
                "CRM_ACCOUNT_ID": crm_account_id,
                "BILLING_COUNTRY": pick(rng, ISO_COUNTRIES),
                "CREATED_AT": created.isoformat(),
                "UPDATED_AT": created.isoformat(),
                **_metadata(rng, extract_date, f"billing/customers_{extract_date}.csv"),
            }
        )
    dataset.tables["billing.customers"] = customers
    null_crm = sum(1 for row in customers if row["CRM_ACCOUNT_ID"] is None)
    dataset.metrics["null_crm_account_id_count"] = null_crm
    dataset.metrics["null_crm_account_id_rate"] = null_crm / customer_count

    # --- Crosswalk with missing billing customers (P3) ---
    crosswalk_count = volumes["crm.account_crosswalk"]
    missing_customers = max(1, round(customer_count * CROSSWALK_MISSING_RATE))
    mapped_customers = [c for c in customers if c["CUSTOMER_ID"] > missing_customers]
    crosswalk: list[dict[str, Any]] = []
    for idx in range(min(crosswalk_count, len(mapped_customers))):
        customer = mapped_customers[idx]
        account = accounts[idx % len(accounts)]
        crosswalk.append(
            {
                "ACCOUNT_ID": account["ACCOUNT_ID"],
                "BILLING_CUSTOMER_ID": customer["CUSTOMER_ID"],
                "CREATED_AT": random_datetime(rng, start, end).isoformat(),
                **_metadata(rng, extract_date, f"crm/account_crosswalk_{extract_date}.csv"),
            }
        )
    dataset.tables["crm.account_crosswalk"] = crosswalk
    dataset.metrics["crosswalk_missing_customers"] = missing_customers
    dataset.metrics["crosswalk_missing_rate"] = missing_customers / customer_count

    # --- Contacts with orphan rate (P5) ---
    contact_count = volumes["crm.contacts"]
    orphan_count = max(1, round(contact_count * ORPHAN_CONTACT_RATE))
    contacts: list[dict[str, Any]] = []
    for idx in range(contact_count):
        account_id = None
        if idx >= orphan_count:
            account_id = accounts[(idx - orphan_count) % len(accounts)]["ACCOUNT_ID"]
        first = pick(rng, ("Alex", "Jordan", "Taylor", "Casey", "Morgan"))
        last = pick(rng, ("Smith", "Johnson", "Lee", "Brown", "Garcia"))
        domain = accounts[idx % len(accounts)]["WEBSITE_DOMAIN"]
        contacts.append(
            {
                "CONTACT_ID": deterministic_uuid(f"contact:{idx}"),
                "ACCOUNT_ID": account_id,
                "FIRST_NAME": first,
                "LAST_NAME": last,
                "EMAIL": fake_email(rng, first, last, domain),
                "PHONE": fake_phone(rng),
                "CREATED_AT": random_datetime(rng, start, end).isoformat(),
                "UPDATED_AT": random_datetime(rng, start, end).isoformat(),
                **_metadata(rng, extract_date, f"crm/contacts_{extract_date}.csv"),
            }
        )
    dataset.tables["crm.contacts"] = contacts
    dataset.metrics["orphan_contact_count"] = orphan_count
    dataset.metrics["orphan_contact_rate"] = orphan_count / contact_count

    # --- Opportunities ---
    opp_count = volumes["crm.opportunities"]
    opportunities: list[dict[str, Any]] = []
    for idx in range(opp_count):
        created = random_datetime(rng, start, end)
        opportunities.append(
            {
                "OPPORTUNITY_ID": deterministic_uuid(f"opp:{idx}"),
                "ACCOUNT_ID": accounts[idx % len(accounts)]["ACCOUNT_ID"],
                "STAGE": pick(rng, STAGES),
                "AMOUNT": round(rng.uniform(1000, 250000), 2),
                "CREATED_AT": created.isoformat(),
                "UPDATED_AT": created.isoformat(),
                **_metadata(rng, extract_date, f"crm/opportunities_{extract_date}.csv"),
            }
        )
    dataset.tables["crm.opportunities"] = opportunities

    # --- Subscriptions (P4 status casing) ---
    sub_count = volumes["billing.subscriptions"]
    subscriptions: list[dict[str, Any]] = []
    for idx in range(sub_count):
        if rng.random() < STATUS_CASE_INCONSISTENCY_RATE:
            status = pick(rng, STATUS_VARIANTS)
        else:
            status = "active"
        start_date = random_date(rng, start, end)
        end_date = None if status.lower() != "cancelled" else random_date(rng, start_date, end)
        subscriptions.append(
            {
                "SUBSCRIPTION_ID": idx + 1,
                "CUSTOMER_ID": customers[idx % len(customers)]["CUSTOMER_ID"],
                "PLAN_CODE": pick(rng, PLAN_CODES),
                "STATUS": status,
                "START_DATE": start_date.isoformat(),
                "END_DATE": end_date.isoformat() if end_date else None,
                "UPDATED_AT": random_datetime(rng, start, end).isoformat(),
                **_metadata(rng, extract_date, f"billing/subscriptions_{extract_date}.csv"),
            }
        )
    dataset.tables["billing.subscriptions"] = subscriptions

    # --- Invoices (P5 unknown customers, P2 null due dates, F1 status column) ---
    invoice_count = volumes["billing.invoices"]
    unknown_count = max(1, round(invoice_count * UNKNOWN_INVOICE_CUSTOMER_RATE))
    invoices_v1: list[dict[str, Any]] = []
    invoices_v2: list[dict[str, Any]] = []
    for idx in range(invoice_count):
        customer_id = -1 if idx < unknown_count else customers[idx % len(customers)]["CUSTOMER_ID"]
        currency = (
            pick(rng, CURRENCY_VARIANTS)
            if rng.random() < CURRENCY_VARIANT_RATE
            else pick_weighted(rng, CURRENCIES, [0.5, 0.35, 0.15])
        )
        issue = random_date(rng, start, end)
        if rng.random() < NULL_DUE_DATE_RATE:
            due = None
        else:
            due = issue.replace(day=min(28, issue.day + 14))
        amount = round(rng.uniform(20, 5000), 2)
        status = pick(rng, INVOICE_STATUSES)
        base = {
            "INVOICE_ID": idx + 1,
            "CUSTOMER_ID": customer_id,
            "CURRENCY": currency,
            "ISSUE_DATE": issue.isoformat(),
            "DUE_DATE": due.isoformat() if due else None,
            "TOTAL_AMOUNT": amount,
            **_metadata(rng, extract_date, f"billing/invoices_{extract_date}.csv"),
        }
        invoices_v1.append({**base, "INVOICE_STATUS": status})
        invoices_v2.append({**base, "STATUS": status})
    dataset.tables["billing.invoices_v1"] = invoices_v1
    dataset.tables["billing.invoices_v2"] = invoices_v2
    dataset.metrics["unknown_invoice_customer_count"] = unknown_count
    dataset.metrics["unknown_invoice_customer_rate"] = unknown_count / invoice_count
    null_due = sum(1 for row in invoices_v1 if row["DUE_DATE"] is None)
    dataset.metrics["null_due_date_count"] = null_due
    dataset.metrics["null_due_date_rate"] = null_due / invoice_count

    # --- Invoice lines ---
    line_count = volumes["billing.invoice_lines"]
    lines_per_invoice = max(1, line_count // max(invoice_count, 1))
    invoice_lines: list[dict[str, Any]] = []
    line_id = 1
    for invoice in invoices_v1:
        for _ in range(lines_per_invoice):
            if line_id > line_count:
                break
            qty = rng.randint(1, 20)
            unit = round(rng.uniform(5, 500), 2)
            period_start = date.fromisoformat(invoice["ISSUE_DATE"])
            period_end = period_start.replace(day=min(28, period_start.day + 27))
            line_extract = (
                date.fromisoformat(BAD_EXTRACT_DATE)
                if line_id % max(line_count // 100, 1) == 0
                else extract_date
            )
            invoice_lines.append(
                {
                    "INVOICE_LINE_ID": line_id,
                    "INVOICE_ID": invoice["INVOICE_ID"],
                    "PLAN_CODE": pick(rng, PLAN_CODES),
                    "QUANTITY": qty,
                    "UNIT_PRICE": unit,
                    "AMOUNT": round(qty * unit, 2),
                    "SERVICE_PERIOD_START": period_start.isoformat(),
                    "SERVICE_PERIOD_END": period_end.isoformat(),
                    **_metadata(
                        rng,
                        line_extract,
                        f"billing/invoice_lines_{line_extract}.csv",
                    ),
                }
            )
            line_id += 1
        if line_id > line_count:
            break
    while len(invoice_lines) < line_count:
        invoice = invoices_v1[len(invoice_lines) % len(invoices_v1)]
        qty = 1
        unit = round(rng.uniform(5, 500), 2)
        invoice_lines.append(
            {
                "INVOICE_LINE_ID": line_id,
                "INVOICE_ID": invoice["INVOICE_ID"],
                "PLAN_CODE": pick(rng, PLAN_CODES),
                "QUANTITY": qty,
                "UNIT_PRICE": unit,
                "AMOUNT": round(qty * unit, 2),
                "SERVICE_PERIOD_START": invoice["ISSUE_DATE"],
                "SERVICE_PERIOD_END": invoice["DUE_DATE"] or invoice["ISSUE_DATE"],
                **_metadata(rng, extract_date, f"billing/invoice_lines_{extract_date}.csv"),
            }
        )
        line_id += 1
    dataset.tables["billing.invoice_lines"] = invoice_lines

    # --- Payments: v1 pre-drift (no late re-deliveries), v2 post-drift (F2 dupes) ---
    payment_count = volumes["payments.payments"]
    duplicate_count = max(1, round(payment_count * DUPLICATE_PAYMENT_RATE))
    payments_v1: list[dict[str, Any]] = []
    payment_id = 1
    for idx in range(payment_count):
        invoice = invoices_v1[idx % len(invoices_v1)]
        paid_at = random_datetime(rng, date.fromisoformat(invoice["ISSUE_DATE"]), end)
        ref = f"PAY-{idx + 1:08d}"
        payments_v1.append(
            {
                "PAYMENT_ID": payment_id,
                "INVOICE_ID": invoice["INVOICE_ID"],
                "PAYMENT_REF": ref,
                "AMOUNT": round(float(invoice["TOTAL_AMOUNT"]) * rng.uniform(0.5, 1.0), 2),
                "PAID_AT": paid_at.isoformat(),
                **_metadata(rng, extract_date, f"payments/payments_{extract_date}.csv"),
            }
        )
        payment_id += 1

    payments_v2 = [dict(row) for row in payments_v1]
    for idx in range(duplicate_count):
        source = payments_v1[idx]
        late_loaded = datetime.fromisoformat(source["_LOADED_AT"]).replace(tzinfo=UTC)
        late_loaded = late_loaded.replace(day=min(28, late_loaded.day + 2))
        payments_v2.append(
            {
                **source,
                "PAYMENT_ID": payment_id,
                "_LOADED_AT": late_loaded.isoformat(),
                "_SOURCE_FILE": f"payments/payments_redelivery_{extract_date}.csv",
            }
        )
        payment_id += 1

    dataset.tables["payments.payments_v1"] = payments_v1
    dataset.tables["payments.payments_v2"] = payments_v2
    dataset.metrics["duplicate_payment_rows"] = duplicate_count
    dataset.metrics["duplicate_payment_rate"] = duplicate_count / payment_count

    # --- Refunds (version-specific payment references) ---
    refund_count = volumes["payments.refunds"]
    refunds_v1: list[dict[str, Any]] = []
    refunds_v2: list[dict[str, Any]] = []
    for idx in range(refund_count):
        payment_v1 = payments_v1[idx % len(payments_v1)]
        payment_v2 = payments_v2[idx % len(payments_v2)]
        refunds_v1.append(
            {
                "REFUND_ID": idx + 1,
                "PAYMENT_ID": payment_v1["PAYMENT_ID"],
                "AMOUNT": round(float(payment_v1["AMOUNT"]) * rng.uniform(0.05, 0.5), 2),
                "REFUNDED_AT": random_datetime(rng, start, end).isoformat(),
                **_metadata(rng, extract_date, f"payments/refunds_{extract_date}.csv"),
            }
        )
        refunds_v2.append(
            {
                "REFUND_ID": idx + 1,
                "PAYMENT_ID": payment_v2["PAYMENT_ID"],
                "AMOUNT": round(float(payment_v2["AMOUNT"]) * rng.uniform(0.05, 0.5), 2),
                "REFUNDED_AT": random_datetime(rng, start, end).isoformat(),
                **_metadata(rng, extract_date, f"payments/refunds_{extract_date}.csv"),
            }
        )
    dataset.tables["payments.refunds_v1"] = refunds_v1
    dataset.tables["payments.refunds_v2"] = refunds_v2

    # --- Support tickets ---
    ticket_count = volumes["support.tickets"]
    tickets: list[dict[str, Any]] = []
    for idx in range(ticket_count):
        tickets.append(
            {
                "TICKET_ID": idx + 1,
                "CUSTOMER_ID": customers[idx % len(customers)]["CUSTOMER_ID"],
                "SUBJECT": f"Support request #{idx + 1}",
                "STATUS": pick(rng, ("open", "pending", "resolved", "closed")),
                "CREATED_AT": random_datetime(rng, start, end).isoformat(),
                **_metadata(rng, extract_date, f"support/tickets_{extract_date}.csv"),
            }
        )
    dataset.tables["support.tickets"] = tickets

    total_rows = sum(len(rows) for key, rows in dataset.tables.items() if not key.endswith("_v2"))
    dataset.metrics["total_rows"] = total_rows
    dataset.metrics["profile"] = config.profile.value
    dataset.metrics["seed"] = config.seed
    return dataset
