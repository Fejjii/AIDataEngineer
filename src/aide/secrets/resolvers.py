"""Scoped, non-enumerable secret resolver interfaces."""

from __future__ import annotations

from typing import Protocol

from pydantic import SecretStr

from aide.secrets.refs import SecretRef, SecretScope


class UnresolvedSecretError(LookupError):
    pass


class ScopeViolationError(PermissionError):
    pass


def assert_scope(ref: SecretRef, allowed: SecretScope) -> None:
    if ref.scope is not allowed:
        raise ScopeViolationError(
            f"secret {ref.name} scope {ref.scope.value} is not {allowed.value}"
        )


class SecretProvider(Protocol):
    """Architecture protocol: resolve(SecretRef) -> SecretStr. No enumeration."""

    def resolve(self, ref: SecretRef) -> SecretStr: ...


SecretResolver = SecretProvider


class ConnectorSecretResolver(Protocol):
    """May resolve CONNECTOR-scoped refs only. Cannot enumerate names."""

    def resolve(self, ref: SecretRef) -> SecretStr: ...


class LlmProviderSecretResolver(Protocol):
    """May resolve LLM_PROVIDER-scoped refs only. Cannot enumerate names."""

    def resolve(self, ref: SecretRef) -> SecretStr: ...


class InMemoryScopedResolver:
    """Test helper. Not a storage implementation."""

    def __init__(self, scope: SecretScope, values: dict[str, str]) -> None:
        self._scope = scope
        self._values = dict(values)

    def resolve(self, ref: SecretRef) -> SecretStr:
        assert_scope(ref, self._scope)
        try:
            return SecretStr(self._values[ref.name])
        except KeyError as exc:
            raise UnresolvedSecretError(ref.name) from exc
