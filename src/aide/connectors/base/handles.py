"""Protocol surfaces that application services may depend on without vendor imports."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.spec import ConnectorSpec
from aide.domain.artifacts import ArtifactProvenance


class WarehouseSurface(Protocol):
    """Health and provenance surface used by the DE002C slice composition."""

    spec: ConnectorSpec

    async def health(self) -> ConnectorHealthSnapshot: ...

    def force_health(self, status: str | None) -> None: ...

    def provenance(
        self,
        *,
        capability_id: str,
        operation_idempotency_key: str,
        resolved_input_digest: str,
        capability_version: int = 1,
        parent_artifact_ids: tuple[UUID, ...] = (),
    ) -> ArtifactProvenance: ...
