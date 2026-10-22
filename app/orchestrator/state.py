from __future__ import annotations

from typing import TypedDict

from app.models.schemas import Task


class GraphState(TypedDict):
    task: Task
    # None keeps the self-loop going; any other value routes to END.
    stop_reason: str | None  # None | "awaiting_approval" | "blocked" | "completed"
