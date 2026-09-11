"""Secret reference and scoped resolver contracts. No storage."""

from aide.secrets.refs import SecretRef, SecretScope
from aide.secrets.resolvers import (
    ConnectorSecretResolver,
    LlmProviderSecretResolver,
    ScopeViolationError,
    SecretProvider,
    SecretResolver,
    UnresolvedSecretError,
    assert_scope,
)

__all__ = [
    "ConnectorSecretResolver",
    "LlmProviderSecretResolver",
    "ScopeViolationError",
    "SecretProvider",
    "SecretRef",
    "SecretResolver",
    "SecretScope",
    "UnresolvedSecretError",
    "assert_scope",
]
