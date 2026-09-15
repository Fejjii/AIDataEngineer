"""Interview MVP benchmark and demo rendering."""

from aide.app.benchmarking.demo import render_demo_report, render_scorecard
from aide.app.benchmarking.runner import (
    assemble_benchmark_result,
    build_fingerprint,
    compare_fingerprints,
    record_run,
    run_interview_once,
    run_offline_benchmark,
)

__all__ = [
    "assemble_benchmark_result",
    "build_fingerprint",
    "compare_fingerprints",
    "record_run",
    "render_demo_report",
    "render_scorecard",
    "run_interview_once",
    "run_offline_benchmark",
]
