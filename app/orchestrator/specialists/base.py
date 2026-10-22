from __future__ import annotations

from app.models.schemas import Subtask, Task


def find_dependency_results(subtask: Subtask, task: Task) -> dict[str, dict]:
    """Results of this subtask's completed dependencies, keyed by subtask id.

    Specialists use this to chain on prior output (e.g. the code specialist
    crunching numbers the data specialist just fetched) without any shared
    mutable state between agents — everything flows through the Task graph.
    """
    by_id = {s.id: s for s in task.subtasks}
    out = {}
    for dep_id in subtask.depends_on:
        dep = by_id.get(dep_id)
        if dep and dep.result is not None:
            out[dep_id] = dep.result
    return out
