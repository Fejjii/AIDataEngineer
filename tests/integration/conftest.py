from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from aide.persistence.database import create_engine, create_session_factory

SYNC_DATABASE_URL = os.getenv(
    "AIDE_TEST_DATABASE_URL",
    "postgresql+psycopg://ubuntu@127.0.0.1:5432/aide_dev",
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", SYNC_DATABASE_URL)
    command.upgrade(config, "head")
    yield


@pytest_asyncio.fixture(scope="session")
async def database_engine(migrated_database: None) -> AsyncIterator[AsyncEngine]:
    del migrated_database
    engine = create_engine(SYNC_DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    database_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    factory = create_session_factory(database_engine)
    async with database_engine.begin() as connection:
        await connection.execute(
            text(
                """
                TRUNCATE TABLE
                    unresolved_effects, recovery_events, task_attempts, artifacts, approvals,
                    template_dispositions, materialized_tasks, task_templates, phase_runs,
                    budget_entries, budget_ledgers, workflow_grants, contract_snapshots,
                    audit_events, audit_sequences, workflows, sessions, connector_health
                RESTART IDENTITY CASCADE
                """
            )
        )
    yield factory
