from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.persistence.database import read_only_unit_of_work


@pytest.mark.asyncio
async def test_read_only_unit_of_work_rejects_writes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(DBAPIError, match="read-only"):
        async with read_only_unit_of_work(session_factory) as session:
            await session.execute(text("CREATE TABLE read_only_probe (id integer)"))
