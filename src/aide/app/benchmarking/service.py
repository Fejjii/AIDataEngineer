"""Env-gated synthetic Interview demo runner. Reuses the offline benchmark path."""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from aide.app.benchmarking.errors import DemoBusyError
from aide.app.benchmarking.runner import run_offline_benchmark
from aide.app.benchmarking.summary import summarize_interview_demo
from aide.domain.benchmark import INTERVIEW_REQUEST, InterviewDemoSummary, LiveSmokeStatus


class SyntheticInterviewDemoService:
    """Run only the accepted synthetic Interview scenario. No client SQL or credentials."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        work_root_factory: Callable[[], Path] | None = None,
    ) -> None:
        self._factory = session_factory
        self._lock = asyncio.Lock()
        self._work_root_factory = work_root_factory or (
            lambda: Path(tempfile.mkdtemp(prefix="aide-interview-demo-"))
        )

    async def run_synthetic_demo(self) -> InterviewDemoSummary:
        if self._lock.locked():
            raise DemoBusyError("synthetic interview demo is already running")
        async with self._lock:
            work_root = self._work_root_factory()
            report, first, _second = await run_offline_benchmark(
                self._factory,
                work_root,
                requirement=INTERVIEW_REQUEST,
                live_smoke=LiveSmokeStatus.NOT_RUN,
                live_smoke_detail="synthetic deployment does not require Snowflake credentials",
            )
            return summarize_interview_demo(report, first)


__all__ = ["SyntheticInterviewDemoService"]
