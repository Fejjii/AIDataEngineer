"""Evaluation tests reuse integration PostgreSQL fixtures.

Pytest 9 forbids ``pytest_plugins`` in non-top-level conftest modules, so the
session fixtures are re-exported here instead of loading
``tests.integration.conftest`` as a nested plugin.
"""

from __future__ import annotations

from tests.integration.conftest import database_engine as database_engine
from tests.integration.conftest import migrated_database as migrated_database
from tests.integration.conftest import session_factory as session_factory

__all__ = ["database_engine", "migrated_database", "session_factory"]
