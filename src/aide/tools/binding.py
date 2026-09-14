"""Connector bindings used by the Governed Tool Gateway.

Bindings hold connector instances at composition time. Application services,
orchestration, generation, repair, and verification import only this protocol.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from aide.connectors.base.context import CallContext, RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec

ReconcileValue = EffectFound | NoEffect | InProgress | Unknown
CapabilityHandler = Callable[[BaseModel, CallContext], Awaitable[BaseModel]]


class ConnectorBinding(Protocol):
    spec: ConnectorSpec | None

    async def health(self) -> ConnectorHealthSnapshot | None: ...

    async def execute(
        self, capability_id: str, payload: BaseModel, context: CallContext
    ) -> BaseModel: ...

    async def cancel(self, capability_id: str, context: CallContext) -> None: ...

    async def reconcile(self, recovery: RecoveryContext) -> ReconcileValue: ...


class AttributeConnectorBinding:
    """Dispatch via ``getattr(connector, capability_id)``. No vendor type imports."""

    def __init__(self, connector: object, spec: ConnectorSpec) -> None:
        self._connector = connector
        self.spec = spec

    async def health(self) -> ConnectorHealthSnapshot | None:
        health = getattr(self._connector, "health", None)
        if health is None:
            return None
        snapshot = await health()
        assert isinstance(snapshot, ConnectorHealthSnapshot)
        return snapshot

    async def execute(
        self, capability_id: str, payload: BaseModel, context: CallContext
    ) -> BaseModel:
        method = getattr(self._connector, capability_id)
        result = await method(payload, context)
        assert isinstance(result, BaseModel)
        return result

    async def cancel(self, capability_id: str, context: CallContext) -> None:
        del capability_id
        cancel = getattr(self._connector, "cancel", None)
        if cancel is None:
            return None
        await cancel(context)
        return None

    async def reconcile(self, recovery: RecoveryContext) -> ReconcileValue:
        reconcile = self._connector.reconcile
        result = await reconcile(recovery)
        if not isinstance(result, (EffectFound, NoEffect, InProgress, Unknown)):
            raise TypeError("connector reconcile returned an untyped result")
        return result


class LocalHandlerBinding:
    """In-process typed handler with no vendor client."""

    def __init__(self, handler: CapabilityHandler) -> None:
        self._handler = handler
        self.spec = None

    async def health(self) -> ConnectorHealthSnapshot | None:
        return None

    async def execute(
        self, capability_id: str, payload: BaseModel, context: CallContext
    ) -> BaseModel:
        del capability_id
        return await self._handler(payload, context)

    async def cancel(self, capability_id: str, context: CallContext) -> None:
        del capability_id, context
        return None

    async def reconcile(self, recovery: RecoveryContext) -> ReconcileValue:
        return NoEffect(evidence=f"local capability {recovery.capability.capability_id}")
