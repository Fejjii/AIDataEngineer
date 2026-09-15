"""Active Interview MVP roadmap contract (PIVOT001 C-09 / AT-22)."""

from __future__ import annotations

ACTIVE_INTERVIEW_TASKS: tuple[str, ...] = ("MVP001", "MVP002", "MVP003", "MVP004")

# Directed edges: (task, depends_on). Sequential and acyclic by construction.
ACTIVE_DEPENDENCY_EDGES: tuple[tuple[str, str], ...] = (
    ("MVP001", "PIVOT001"),
    ("MVP002", "MVP001"),
    ("MVP003", "MVP002"),
    ("MVP004", "MVP003"),
)

DEFERRED_AFTER_MVP004: tuple[str, ...] = (
    "DE008B",
    "DE009",
    "DE010",
    "DE011",
    "DE012",
    "DE013",
    "DE014",
    "DE015",
    "DE016",
    "DE017",
    "DE018",
    "DE019",
)


def dependency_graph_is_acyclic(edges: tuple[tuple[str, str], ...]) -> bool:
    incoming: dict[str, set[str]] = {}
    nodes: set[str] = set()
    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)
        incoming.setdefault(src, set()).add(dst)
        incoming.setdefault(dst, set())
    remaining = set(nodes)
    while remaining:
        ready = [node for node in sorted(remaining) if not incoming[node]]
        if not ready:
            return False
        node = ready[0]
        remaining.remove(node)
        for src, dst in edges:
            if dst == node:
                incoming[src].discard(node)
    return True


def dependencies_are_sequential(tasks: tuple[str, ...], edges: tuple[tuple[str, str], ...]) -> bool:
    """Each MVP task depends only on its immediate predecessor (plus PIVOT001 for MVP001)."""
    index = {task: i for i, task in enumerate(tasks)}
    for src, dst in edges:
        if src not in index:
            return False
        if dst == "PIVOT001":
            if src != tasks[0]:
                return False
            continue
        if dst not in index:
            return False
        if index[src] != index[dst] + 1:
            return False
    return True


__all__ = [
    "ACTIVE_DEPENDENCY_EDGES",
    "ACTIVE_INTERVIEW_TASKS",
    "DEFERRED_AFTER_MVP004",
    "dependencies_are_sequential",
    "dependency_graph_is_acyclic",
]
