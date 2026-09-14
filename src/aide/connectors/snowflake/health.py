"""Health snapshots. Missing credentials expose env var names only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from aide.connectors.base.health import ConnectorHealthSnapshot, HealthStatus
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.snowflake.config import SnowflakeSettings, missing_secret_names
from aide.connectors.snowflake.dialect import normalize_identifier

HEALTH_TTL = timedelta(minutes=5)
ROLE_MISMATCH = "ROLE_MISMATCH"
HEALTH_EMPTY_RESULT = "HEALTH_EMPTY_RESULT"


def _now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def health_snapshot(
    spec: ConnectorSpec,
    *,
    status: HealthStatus,
    reason_codes: tuple[str, ...] = (),
) -> ConnectorHealthSnapshot:
    now = _now_naive()
    return ConnectorHealthSnapshot(
        connector_id=spec.connector_id,
        status=status,
        checked_at=now,
        expires_at=now + HEALTH_TTL,
        reason_codes=reason_codes,
    )


def missing_credential_health(
    spec: ConnectorSpec, settings: SnowflakeSettings
) -> ConnectorHealthSnapshot | None:
    missing = missing_secret_names(settings)
    if not missing:
        return None
    return health_snapshot(
        spec,
        status="UNAVAILABLE",
        reason_codes=tuple(f"SECRET_UNRESOLVED:{name}" for name in missing),
    )


def current_role_from_rows(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    row = rows[0]
    value = row.get("ROLE")
    if value is None:
        value = row.get("CURRENT_ROLE")
    if value is None and row:
        value = next(iter(row.values()), None)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def roles_match(current_role: str, expected_role: str) -> bool:
    return normalize_identifier(current_role) == normalize_identifier(expected_role)


def health_from_current_role(
    spec: ConnectorSpec, *, expected_role: str, current_role: str | None
) -> ConnectorHealthSnapshot:
    """Fail closed unless CURRENT_ROLE matches the connector identity role."""
    if current_role is None:
        return health_snapshot(spec, status="DEGRADED", reason_codes=(HEALTH_EMPTY_RESULT,))
    if not roles_match(current_role, expected_role):
        return health_snapshot(spec, status="UNAVAILABLE", reason_codes=(ROLE_MISMATCH,))
    return health_snapshot(spec, status="AVAILABLE")
