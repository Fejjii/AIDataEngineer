"""Phase packages."""

from aide.orchestration.phases.design import (
    DESIGN_EXIT_CRITERIA,
    build_design_plan,
    build_design_templates,
)
from aide.orchestration.phases.profiling import (
    PROFILING_EXIT_CRITERIA,
    allocate_profiling_slots,
    build_profiling_plan,
    build_profiling_templates,
)

__all__ = [
    "DESIGN_EXIT_CRITERIA",
    "PROFILING_EXIT_CRITERIA",
    "allocate_profiling_slots",
    "build_design_plan",
    "build_design_templates",
    "build_profiling_plan",
    "build_profiling_templates",
]
