"""Shapes the operator console HTTP layer is allowed to depend on."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from aide.auth.context import TrustedAuthenticationContext
from aide.auth.session import IssuedLocalSession


class ConsoleSession(Protocol):
    """Session operations the console needs beyond anonymous workflow submit."""

    @property
    def csrf_secret(self) -> bytes: ...

    async def open_session(
        self,
        opaque_token: str | None,
    ) -> tuple[object, TrustedAuthenticationContext]: ...

    async def authenticate(
        self,
        opaque_token: str | None,
        *,
        csrf_token: str | None,
        method: str,
    ) -> TrustedAuthenticationContext: ...

    async def csrf_token_for(self, opaque_token: str | None) -> str: ...

    async def revoke(self, opaque_token: str | None) -> None: ...


class ConsoleExport(Protocol):
    """Read-only export body. Matches frozen export records without a runtime wrapper."""

    @property
    def body(self) -> bytes: ...

    @property
    def media_type(self) -> str: ...

    @property
    def filename(self) -> str: ...


class ConsolePort(Protocol):
    """Fixed-scenario runs. The concrete service lives outside the API layer."""

    def password_configured(self) -> bool: ...

    def password_matches(self, provided: str) -> bool: ...

    async def issue_operator_session(self) -> IssuedLocalSession: ...

    def source_catalog(self) -> object: ...

    async def list_runs(self) -> object: ...

    async def start_run(self, principal_id: UUID) -> UUID: ...

    async def reconcile_interrupted_runs(self) -> None: ...

    async def run_page(self, run_id: UUID) -> object | None: ...

    async def export(self, run_id: UUID, name: str) -> ConsoleExport | None: ...
