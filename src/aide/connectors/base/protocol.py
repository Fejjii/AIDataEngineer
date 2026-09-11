"""Connector protocol. No vendor implementation in DE 002A."""

from __future__ import annotations

from typing import Protocol

from aide.connectors.base.context import RecoveryContext
from aide.connectors.base.health import ConnectorHealthSnapshot
from aide.connectors.base.reconcile import EffectFound, InProgress, NoEffect, Unknown
from aide.connectors.base.spec import ConnectorSpec


class Connector(Protocol):
    spec: ConnectorSpec

    async def health(self) -> ConnectorHealthSnapshot: ...

    async def reconcile(
        self, recovery: RecoveryContext
    ) -> EffectFound | NoEffect | InProgress | Unknown: ...

    async def close(self) -> None: ...
