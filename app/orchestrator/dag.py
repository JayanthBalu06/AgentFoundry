"""Dependency-DAG scheduling over a task's subtasks.

The supervisor produces subtasks with `depends_on` edges; this module is the
only place that decides which subtasks are runnable right now, so the
scheduling logic (and its cycle/missing-dependency checks) isn't duplicated
between the API, the Celery worker, and tests.
"""
from __future__ import annotations

from app.models.schemas import Subtask, SubtaskStatus


class DAGValidationError(Exception):
    pass


def validate_dag(subtasks: list[Subtask]) -> None:
    ids = {s.id for s in subtasks}
    for s in subtasks:
        for dep in s.depends_on:
            if dep not in ids:
                raise DAGValidationError(f"subtask '{s.id}' depends on unknown subtask '{dep}'")
    _topological_order(subtasks)  # raises DAGValidationError on a cycle


def _topological_order(subtasks: list[Subtask]) -> list[str]:
    remaining = {s.id: set(s.depends_on) for s in subtasks}
    ordered: list[str] = []
    while remaining:
        ready = [sid for sid, deps in remaining.items() if not deps]
        if not ready:
            raise DAGValidationError(f"cycle detected among: {sorted(remaining)}")
        for sid in sorted(ready):
            ordered.append(sid)
            del remaining[sid]
        for deps in remaining.values():
            deps.difference_update(ready)
    return ordered


def get_ready_subtasks(subtasks: list[Subtask]) -> list[Subtask]:
    """Subtasks that are PENDING and whose dependencies have all COMPLETED."""
    completed = {s.id for s in subtasks if s.status == SubtaskStatus.COMPLETED}
    ready = []
    for s in subtasks:
        if s.status != SubtaskStatus.PENDING:
            continue
        if set(s.depends_on).issubset(completed):
            ready.append(s)
    return ready


def is_blocked(subtasks: list[Subtask]) -> bool:
    """True if nothing is runnable, nothing is in flight, and work remains.

    This signals a stuck DAG (e.g. every remaining subtask depends on one
    that FAILED permanently) rather than a transient waiting state.
    """
    unfinished = [s for s in subtasks if s.status not in (SubtaskStatus.COMPLETED, SubtaskStatus.FAILED)]
    if not unfinished:
        return False
    in_flight = any(
        s.status in (SubtaskStatus.RUNNING, SubtaskStatus.REVIEWING, SubtaskStatus.AWAITING_APPROVAL, SubtaskStatus.READY)
        for s in unfinished
    )
    if in_flight:
        return False
    return len(get_ready_subtasks(subtasks)) == 0


def all_complete(subtasks: list[Subtask]) -> bool:
    return all(s.status == SubtaskStatus.COMPLETED for s in subtasks)


def any_failed_permanently(subtasks: list[Subtask]) -> bool:
    return any(s.status == SubtaskStatus.FAILED for s in subtasks)
