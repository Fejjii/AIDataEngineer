"""Deterministic random helpers for seeded generation."""

from __future__ import annotations

import random
import uuid
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta

VANTARA_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def seeded_rng(seed: int) -> random.Random:
    return random.Random(seed)


def deterministic_uuid(seed_text: str) -> str:
    return str(uuid.uuid5(VANTARA_NAMESPACE, seed_text))


def deterministic_uuids(prefix: str, count: int) -> Iterator[str]:
    for index in range(count):
        yield deterministic_uuid(f"{prefix}:{index}")


def pick(rng: random.Random, items: Sequence[str]) -> str:
    return items[rng.randrange(len(items))]


def pick_weighted(rng: random.Random, items: Sequence[str], weights: Sequence[float]) -> str:
    return rng.choices(items, weights=weights, k=1)[0]


def random_date(rng: random.Random, start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, max(delta, 0)))


def random_datetime(rng: random.Random, start: date, end: date) -> datetime:
    day = random_date(rng, start, end)
    return datetime(
        day.year,
        day.month,
        day.day,
        rng.randint(0, 23),
        rng.randint(0, 59),
        rng.randint(0, 59),
        tzinfo=UTC,
    )


def fake_email(rng: random.Random, first: str, last: str, domain: str) -> str:
    slug = f"{first}.{last}".lower().replace(" ", "")
    suffix = rng.randint(1, 9999)
    return f"{slug}{suffix}@{domain}"


def fake_phone(rng: random.Random) -> str:
    return f"+{rng.randint(1, 99)}-{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}"


def fake_company_name(rng: random.Random, index: int) -> str:
    stems = ("Nova", "Bright", "Summit", "Vertex", "Clear", "Prime", "Atlas", "Pulse")
    suffixes = ("Systems", "Labs", "Group", "Works", "Cloud", "Analytics", "Digital")
    return f"{stems[index % len(stems)]} {suffixes[(index // len(stems)) % len(suffixes)]}"


def fake_domain(rng: random.Random, company: str, index: int) -> str:
    base = company.lower().replace(" ", "")
    tlds = ("com", "io", "co.uk", "de", "fr")
    return f"{base}{index % 17}.{pick(rng, tlds)}"


def normalize_domain(domain: str) -> str:
    return domain.lower().strip().removeprefix("www.")
