"""Explicit query, sample, and time budgets for profiling."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from aide.capabilities.io import Budget
from aide.domain.failures import FailureClass


class ProfilingBudgetExceeded(RuntimeError):
    """Raised when a profiling budget is exhausted."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.failure_class = FailureClass.RESOURCE_LIMIT


@dataclass(frozen=True, slots=True)
class ProfilingBudget:
    max_rows: int
    max_bytes: int
    max_seconds: int
    max_queries: int
    max_pairs: int
    sample_n: int
    sample_asset_limit: int
    top_k: int
    sample_bytes: int = 65_536

    def __post_init__(self) -> None:
        if self.sample_n > 20:
            raise ProfilingBudgetExceeded("sample_dataset n must be <= 20")
        if self.sample_n < 1:
            raise ProfilingBudgetExceeded("sample_dataset n must be >= 1")
        if self.max_queries < 1 or self.max_pairs < 1:
            raise ProfilingBudgetExceeded("query and pair budgets must be >= 1")

    def capability_budget(self) -> Budget:
        return Budget(
            max_rows=self.max_rows,
            max_bytes=self.max_bytes,
            max_seconds=self.max_seconds,
        )

    def halved(self) -> ProfilingBudget:
        return ProfilingBudget(
            max_rows=max(1, self.max_rows // 2),
            max_bytes=max(1, self.max_bytes // 2),
            max_seconds=max(1, self.max_seconds // 2),
            max_queries=max(1, self.max_queries // 2),
            max_pairs=max(1, self.max_pairs // 2),
            sample_n=self.sample_n,
            sample_asset_limit=self.sample_asset_limit,
            top_k=max(1, self.top_k // 2),
            sample_bytes=max(1024, self.sample_bytes // 2),
        )


TINY_OFFLINE_BUDGET = ProfilingBudget(
    max_rows=10_000,
    max_bytes=1_000_000,
    max_seconds=60,
    max_queries=400,
    max_pairs=80,
    sample_n=20,
    sample_asset_limit=3,
    top_k=10,
)


@dataclass
class BudgetTracker:
    budget: ProfilingBudget
    queries: int = 0
    pairs: int = 0
    started: float = field(default_factory=perf_counter)

    def charge_query(self) -> None:
        self._check_time()
        if self.queries >= self.budget.max_queries:
            raise ProfilingBudgetExceeded(
                f"max_queries={self.budget.max_queries} exhausted after {self.queries} queries"
            )
        self.queries += 1

    def charge_pair(self) -> None:
        if self.pairs >= self.budget.max_pairs:
            raise ProfilingBudgetExceeded(
                f"max_pairs={self.budget.max_pairs} exhausted after {self.pairs} pairs"
            )
        self.pairs += 1

    def _check_time(self) -> None:
        elapsed = perf_counter() - self.started
        if elapsed > self.budget.max_seconds:
            raise ProfilingBudgetExceeded(
                f"max_seconds={self.budget.max_seconds} exceeded ({elapsed:.3f}s)"
            )

    def elapsed_seconds(self) -> float:
        return perf_counter() - self.started

    def usage(self) -> dict[str, int | float]:
        return {
            "queries": self.queries,
            "pairs": self.pairs,
            "elapsed_seconds": round(self.elapsed_seconds(), 4),
            "max_queries": self.budget.max_queries,
            "max_pairs": self.budget.max_pairs,
            "max_seconds": self.budget.max_seconds,
            "sample_n": self.budget.sample_n,
        }
