"""In-memory capability registry. Duplicate (id, version) fails registration."""

from __future__ import annotations

from aide.capabilities.spec import CapabilitySpec
from aide.domain.permissions import PermissionLevel


class DuplicateCapabilityError(ValueError):
    pass


class UnknownCapabilityError(KeyError):
    pass


class CapabilityRegistry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, int], CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        key = (spec.id, spec.version)
        if key in self._specs:
            raise DuplicateCapabilityError(f"duplicate capability {spec.id}@{spec.version}")
        self._specs[key] = spec

    def get(self, capability_id: str, version: int) -> CapabilitySpec:
        try:
            return self._specs[(capability_id, version)]
        except KeyError as exc:
            raise UnknownCapabilityError(f"{capability_id}@{version}") from exc

    def contains(self, capability_id: str, version: int) -> bool:
        return (capability_id, version) in self._specs

    def latest(self, capability_id: str) -> CapabilitySpec | None:
        versions = [spec for (cid, _), spec in self._specs.items() if cid == capability_id]
        if not versions:
            return None
        return max(versions, key=lambda spec: spec.version)

    def all_specs(self) -> tuple[CapabilitySpec, ...]:
        return tuple(self._specs.values())

    def required_permissions(self) -> dict[str, PermissionLevel]:
        return {spec.id: spec.required_permission for spec in self._specs.values()}
