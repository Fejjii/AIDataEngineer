"""One read-only Snowflake session owned by a single worker thread."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_SessionOpener = Callable[[str, int], Any]
_Call = tuple[Callable[[Any], Any], str, int, asyncio.AbstractEventLoop, asyncio.Future[Any]]


def _deliver(
    loop: asyncio.AbstractEventLoop,
    future: asyncio.Future[Any],
    *,
    result: Any = None,
    error: BaseException | None = None,
) -> None:
    def finish() -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
            return
        future.set_result(result)

    loop.call_soon_threadsafe(finish)


class PinnedReadSession:
    """Reuse one vendor session for sequential read-only calls.

    The Snowflake connection is not thread-safe, so every call runs on the
    thread that opened it.
    """

    def __init__(self, opener: _SessionOpener) -> None:
        self._opener = opener
        self._queue: queue.Queue[_Call | None] = queue.Queue()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run, name="aide-snowflake-read-session", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        session: Any = None
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                fn, query_tag, timeout_seconds, loop, future = item
                if future.cancelled():
                    continue
                try:
                    if session is None:
                        session = self._opener(query_tag, timeout_seconds)
                    prepare = getattr(session, "prepare", None)
                    if prepare is not None:
                        prepare(query_tag=query_tag, timeout_seconds=timeout_seconds)
                    result = fn(session)
                except Exception as exc:
                    _deliver(loop, future, error=exc)
                else:
                    _deliver(loop, future, result=result)
        finally:
            if session is not None:
                session.close()

    async def call(self, fn: Callable[..., T], *, query_tag: str, timeout_seconds: int) -> T:
        if self._closed:
            raise RuntimeError("read session is closed")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[T] = loop.create_future()
        self._queue.put((fn, query_tag, timeout_seconds, loop, future))
        return await future

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._queue.put(None)
        await asyncio.to_thread(self._thread.join, 30)
