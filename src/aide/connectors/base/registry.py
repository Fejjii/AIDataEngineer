"""In-memory connector advertisements and R0 startup permission check."""

from __future__ import annotations

from collections.abc import Mapping

from aide.connectors.base.spec import ConnectorSpec
from aide.domain.permissions import PermissionLevel


class DuplicateConnectorError(ValueError):
    pass


class UnknownConnectorError(KeyError):
    pass


class ConnectorPermissionConfigError(ValueError):
    """R0: advertised capability permission not in allowed_permissions."""


class ConnectorRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ConnectorSpec] = {}

    def register(
        self,
        spec: ConnectorSpec,
        required_permissions: Mapping[str, PermissionLevel] | None = None,
    ) -> None:
        if spec.connector_id in self._specs:
            raise DuplicateConnectorError(spec.connector_id)
        if required_permissions is not None:
            startup_permission_check(spec, required_permissions)
        self._specs[spec.connector_id] = spec

    def get(self, connector_id: str) -> ConnectorSpec:
        try:
            return self._specs[connector_id]
        except KeyError as exc:
            raise UnknownConnectorError(connector_id) from exc

    def contains(self, connector_id: str) -> bool:
        return connector_id in self._specs

    def all_specs(self) -> tuple[ConnectorSpec, ...]:
        return tuple(self._specs.values())


def startup_permission_check(
    spec: ConnectorSpec, required_permissions: Mapping[str, PermissionLevel]
) -> None:
    """R0 — misconfiguration, never reached at runtime if registration succeeded."""
    for impl in spec.implementations:
        required = required_permissions.get(impl.capability_id)
        if required is None:
            continue
        if required not in spec.allowed_permissions:
            raise ConnectorPermissionConfigError(
                f"{spec.connector_id} advertises {impl.capability_id} requiring "
                f"{required.value} which is not in allowed_permissions"
            )
