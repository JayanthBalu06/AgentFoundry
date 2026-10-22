"""API specialist: delegates to the `api_call` tool.

In mock mode (no LLM configured) it still makes a *real* HTTP call — to a
safe, public, read-only endpoint — so the API tool path is genuinely
exercised end to end rather than stubbed out.
"""
from __future__ import annotations

import re

from app.models.schemas import Subtask, Task
from app.orchestrator.specialists.base import find_dependency_results
from app.tools.registry import ToolCallResult, get_tool_registry

_URL_RE = re.compile(r"https?://\S+")
_DEFAULT_URL = "https://httpbin.org/get"


def run(subtask: Subtask, task: Task) -> ToolCallResult:
    registry = get_tool_registry()
    explicit = _URL_RE.search(subtask.description) or _URL_RE.search(subtask.title)
    url = explicit.group(0) if explicit else _DEFAULT_URL

    deps = find_dependency_results(subtask, task)
    params = {"task_id": task.id, "subtask": subtask.id}
    if deps:
        params["upstream_subtasks"] = ",".join(deps.keys())

    return registry.call(
        "api_call",
        agent="api_specialist",
        task_id=task.id,
        url=url,
        method="GET",
        params=params,
    )
