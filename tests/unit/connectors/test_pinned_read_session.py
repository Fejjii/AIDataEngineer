from __future__ import annotations

import asyncio

from aide.connectors.snowflake.read_session import PinnedReadSession


def test_pinned_read_session_opens_once() -> None:
    opened: list[str] = []

    class _Session:
        def prepare(self, *, query_tag: str, timeout_seconds: int) -> None:
            del query_tag, timeout_seconds

        def execute(self, sql: str) -> str:
            return sql

        def close(self) -> None:
            opened.append("closed")

    def opener(query_tag: str, timeout_seconds: int) -> _Session:
        del query_tag, timeout_seconds
        opened.append("open")
        return _Session()

    async def run() -> None:
        lease = PinnedReadSession(opener)
        first = await lease.call(
            lambda session: session.execute("one"), query_tag="a", timeout_seconds=5
        )
        second = await lease.call(
            lambda session: session.execute("two"), query_tag="b", timeout_seconds=4
        )
        await lease.close()
        assert first == "one"
        assert second == "two"

    asyncio.run(run())
    assert opened.count("open") == 1
    assert opened[-1] == "closed"
