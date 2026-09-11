from __future__ import annotations

import pytest
from pydantic import SecretStr

from aide.secrets.refs import SecretRef, SecretScope
from aide.secrets.resolvers import (
    InMemoryScopedResolver,
    ScopeViolationError,
    UnresolvedSecretError,
)


def test_connector_and_llm_scopes_are_separated() -> None:
    connector = InMemoryScopedResolver(
        SecretScope.CONNECTOR, {"SNOWFLAKE_DEV_PRIVATE_KEY": "connector-secret"}
    )
    llm = InMemoryScopedResolver(SecretScope.LLM_PROVIDER, {"LLM_API_KEY": "llm-secret"})
    connector_ref = SecretRef(name="SNOWFLAKE_DEV_PRIVATE_KEY", scope=SecretScope.CONNECTOR)
    llm_ref = SecretRef(name="LLM_API_KEY", scope=SecretScope.LLM_PROVIDER)
    assert connector.resolve(connector_ref) == SecretStr("connector-secret")
    assert llm.resolve(llm_ref) == SecretStr("llm-secret")
    with pytest.raises(ScopeViolationError):
        connector.resolve(llm_ref)
    with pytest.raises(ScopeViolationError):
        llm.resolve(connector_ref)
    with pytest.raises(UnresolvedSecretError):
        connector.resolve(SecretRef(name="MISSING_CONNECTOR_SECRET", scope=SecretScope.CONNECTOR))
    assert not hasattr(connector, "list")
    assert not hasattr(connector, "enumerate")
