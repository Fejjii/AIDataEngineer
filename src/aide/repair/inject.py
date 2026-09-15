"""Protocol for injecting the accepted Interview MVP schema drift.

Implementations live in the composition root so Supervisor never imports fakes.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class SchemaDriftInjector(Protocol):
    def inject_invoice_status_rename(self, workflow_id: UUID) -> None: ...
