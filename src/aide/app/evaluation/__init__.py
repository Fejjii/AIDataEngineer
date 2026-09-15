"""Interview MVP evaluation scorecard aggregation."""

from aide.app.evaluation.catalog import CATEGORY_OPTIONAL, CATEGORY_REQUIRED
from aide.app.evaluation.report import render_evaluation_markdown
from aide.app.evaluation.scorecard import build_evaluation_report, score_categories

__all__ = [
    "CATEGORY_OPTIONAL",
    "CATEGORY_REQUIRED",
    "build_evaluation_report",
    "render_evaluation_markdown",
    "score_categories",
]
