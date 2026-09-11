"""TTL-bound connector health snapshot."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aide.domain.permissions import PermissionLevel

HealthStatus = Literal["AVAILABLE", "DEGRADED", "UNAVAILABLE", "MOCK"]


class ConnectorHealthSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: str = Field(min_length=1)
    status: HealthStatus
    checked_at: datetime
    expires_at: datetime
    missing_permissions: frozenset[PermissionLevel] = frozenset()
    reason_codes: tuple[str, ...] = ()

    def is_expired(self, now: datetime) -> bool:
        return now >= self.expires_at

    def execution_ready(self, now: datetime) -> bool:
        if self.is_expired(now):
            return False
        return self.status in {"AVAILABLE", "DEGRADED", "MOCK"}
