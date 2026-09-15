"""Render a concise deterministic evaluation markdown report. No LLM judge."""

from __future__ import annotations

from aide.domain.evaluation import EvaluationReport, EvaluationVerdict


def render_evaluation_markdown(report: EvaluationReport) -> str:
    lines = [
        f"# Interview MVP evaluation — {report.task_id}",
        "",
        f"**Readiness:** `{report.readiness.value}`",
        "",
        "## Evaluation matrix",
        "",
        "| Category | Verdict | Evidence |",
        "|---|---|---|",
    ]
    for row in report.categories:
        evidence = row.evidence.replace("|", "/")
        lines.append(f"| `{row.category.value}` | `{row.verdict.value}` | {evidence} |")
    lines.extend(
        ["", "## Scenarios", "", "| ID | Name | Verdict | Evidence |", "|---|---|---|---|"]
    )
    for item in report.scenarios:
        evidence = item.evidence.replace("|", "/")
        lines.append(
            f"| `{item.scenario_id}` | {item.name} | `{item.verdict.value}` | {evidence} |"
        )
    lines.extend(["", "## Defects discovered", ""])
    if report.defects_found:
        lines.extend(f"- {item}" for item in report.defects_found)
    else:
        lines.append("- None")
    lines.extend(["", "## Defects fixed", ""])
    if report.defects_fixed:
        lines.extend(f"- {item}" for item in report.defects_fixed)
    else:
        lines.append("- None")
    lines.extend(["", "## Remaining risks", ""])
    if report.remaining_risks:
        lines.extend(f"- {item}" for item in report.remaining_risks)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Benchmark summary",
            "",
            report.benchmark_summary,
            "",
            "## Performance summary",
            "",
            report.performance_summary,
            "",
            "## Known limitations",
            "",
        ]
    )
    if report.known_limitations:
        lines.extend(f"- {item}" for item in report.known_limitations)
    else:
        lines.append("- None")
    failed = [item for item in report.categories if item.verdict is EvaluationVerdict.FAIL]
    lines.extend(["", "## Final MVP readiness verdict", "", f"`{report.readiness.value}`"])
    if failed:
        names = ", ".join(item.category.value for item in failed)
        lines.append(f"Failed categories: {names}")
    lines.append("")
    return "\n".join(lines)


__all__ = ["render_evaluation_markdown"]
