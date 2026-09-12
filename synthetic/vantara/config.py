"""Scale profiles and volume targets for the Vantara synthetic generator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

DEFAULT_SEED = 20260401
PACKAGE_ROOT = Path(__file__).resolve().parent
SYNTHETIC_ROOT = PACKAGE_ROOT.parent


class Profile(StrEnum):
    TINY = "tiny"
    DEMO = "demo"
    FULL = "full"


# Full-profile row targets from docs/DEMO_COMPANY.md §2 (USAGE disabled).
FULL_TABLE_VOLUMES: dict[str, int] = {
    "crm.accounts": 27_500,
    "crm.contacts": 82_000,
    "crm.opportunities": 41_000,
    "crm.account_crosswalk": 24_900,
    "billing.customers": 25_600,
    "billing.subscriptions": 61_000,
    "billing.invoices": 1_240_000,
    "billing.invoice_lines": 4_100_000,
    "payments.payments": 1_130_000,
    "payments.refunds": 38_000,
    "product.plans": 96,
    "support.tickets": 310_000,
}

PROFILE_FACTORS: dict[Profile, float] = {
    Profile.TINY: 0.005,
    Profile.DEMO: 0.10,
    Profile.FULL: 1.0,
}

PROFILE_TOTAL_TARGETS: dict[Profile, int] = {
    Profile.TINY: 35_000,
    Profile.DEMO: 690_000,
    Profile.FULL: 6_900_000,
}

# Planted-problem rates — invariant across profiles (docs/DEMO_COMPANY.md §4).
DUPLICATE_ACCOUNT_RATE = 0.07
ORPHAN_CONTACT_RATE = 0.02
CROSSWALK_MISSING_RATE = 0.031
UNKNOWN_INVOICE_CUSTOMER_RATE = 0.004
DUPLICATE_PAYMENT_RATE = 0.015
NULL_CRM_ACCOUNT_ID_RATE = 0.12
NULL_DUE_DATE_RATE = 0.03
STATUS_CASE_INCONSISTENCY_RATE = 0.08
CURRENCY_VARIANT_RATE = 0.06

# Schema drift timing (F1).
DRIFT_EFFECTIVE_DATE = "2026-07-01"
BAD_EXTRACT_DATE = "2026-06-15"


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    profile: Profile
    seed: int
    factor: float
    table_volumes: dict[str, int]
    target_total_rows: int
    output_root: Path

    @property
    def committable(self) -> bool:
        return self.profile is Profile.TINY


def scale_volume(full_count: int, factor: float) -> int:
    """Scale a full-profile count, preserving at least one row when full > 0."""
    if full_count == 0:
        return 0
    if factor >= 1.0:
        return full_count
    scaled = max(1, round(full_count * factor))
    return scaled


def profile_config(
    profile: Profile | str,
    *,
    seed: int = DEFAULT_SEED,
    output_root: Path | None = None,
) -> ProfileConfig:
    resolved = Profile(profile)
    factor = PROFILE_FACTORS[resolved]
    volumes = {
        key: scale_volume(count, factor) if key != "product.plans" else count
        for key, count in FULL_TABLE_VOLUMES.items()
    }
    root = output_root or (PACKAGE_ROOT / "fixtures" / resolved.value)
    return ProfileConfig(
        profile=resolved,
        seed=seed,
        factor=factor,
        table_volumes=volumes,
        target_total_rows=PROFILE_TOTAL_TARGETS[resolved],
        output_root=root,
    )
