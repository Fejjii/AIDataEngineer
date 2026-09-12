"""Health snapshots. Missing credentials expose env var names only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aide.connectors.base.health import ConnectorHealthSnapshot, HealthStatus
from aide.connectors.base.spec import ConnectorSpec
from aide.connectors.snowflake.config import SnowflakeSettings, missing_secret_names

HEALTH_TTL = timedelta(minutes=5)


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
