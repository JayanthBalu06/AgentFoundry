"""Supervisor agent: decomposes a goal into a dependency-DAG of subtasks
(planning), and later synthesizes the specialists' results into one answer
(synthesis). Consults long-term memory while planning so prior corrections
and successful approaches for this user inform the new plan.
"""
from __future__ import annotations

import json

from app.config import get_settings
from app.llm.client import get_llm_client
from app.memory.long_term_memory import get_long_term_memory
from app.models.schemas import SpecialistType, Subtask, Task

_SENSITIVE_KEYWORDS = ("production", "payment", "delete", "irreversible", "legal", "credential")

_SYSTEM_PROMPT = (
    "You are the supervisor of a multi-agent system with three specialists: "
    "'api' (calls external HTTP APIs), 'data' (runs read-only SQL), and 'code' "
    "(runs sandboxed Python for analysis/computation). Decompose the user's goal "
    "into 2-5 subtasks forming a dependency DAG. Return ONLY JSON: "
    '{"confidence": <0..1>, "subtasks": [{"id": "t1", "title": "...", '
    '"description": "...", "specialist": "api|data|code", "depends_on": ["t0"]}]}'
)


def _heuristic_plan(goal: str) -> tuple[float, list[Subtask]]:
    """Deterministic fallback plan used when no LLM provider is configured.

    Builds a representative 3-stage pipeline (fetch data -> analyze -> report)
    so the DAG-scheduling and dependency-passing machinery is always
    exercisable offline, while still reading as tailored to the goal text.
    """
    data_task = Subtask(
        title="Gather relevant data",
        description=f"Query the demo database for records relevant to: {goal}",
        specialist=SpecialistType.DATA,
    )
    code_task = Subtask(
        title="Analyze the data",
        description=f"Compute summary statistics relevant to: {goal}",
        specialist=SpecialistType.CODE,
        depends_on=[data_task.id],
    )
    api_task = Subtask(
        title="Report the result",
        description=f"Send the analysis result onward for: {goal}",
        specialist=SpecialistType.API,
        depends_on=[code_task.id],
    )

    confidence = 0.85
    if any(kw in goal.lower() for kw in _SENSITIVE_KEYWORDS):
        confidence -= 0.35

    return confidence, [data_task, code_task, api_task]


def _llm_plan(goal: str) -> tuple[float, list[Subtask]]:
    client = get_llm_client()
    response = client.complete(system=_SYSTEM_PROMPT, prompt=f"Goal: {goal}")
    data = json.loads(response.text)
    subtasks = [
        Subtask(
            id=item["id"],
            title=item["title"],
            description=item["description"],
            specialist=SpecialistType(item["specialist"]),
            depends_on=item.get("depends_on", []),
        )
        for item in data["subtasks"]
    ]
    return float(data.get("confidence", 0.75)), subtasks


def plan(task: Task) -> Task:
    settings = get_settings()

    memory = get_long_term_memory()
    prior = memory.query(task.user_id, task.goal, top_k=3)
    if prior:
        task_note = "; ".join(p["text"] for p in prior)
        task = task.model_copy(update={"goal": f"{task.goal}\n\n[relevant prior context: {task_note}]"})

    if settings.llm_provider == "mock":
        confidence, subtasks = _heuristic_plan(task.goal)
    else:
        try:
            confidence, subtasks = _llm_plan(task.goal)
        except Exception:  # noqa: BLE001 - never let a bad LLM response crash planning
            confidence, subtasks = _heuristic_plan(task.goal)

    task.plan_confidence = confidence
    task.subtasks = subtasks
    return task


def synthesize(task: Task) -> str:
    settings = get_settings()
    completed = [s for s in task.subtasks if s.status.value == "completed"]

    if settings.llm_provider == "mock" or not completed:
        lines = [f"Goal: {task.goal}", "", "Results:"]
        for s in completed:
            lines.append(f"- {s.title}: {json.dumps(s.result)[:300]}")
        return "\n".join(lines)

    client = get_llm_client()
    context = "\n".join(f"{s.title}: {json.dumps(s.result)[:500]}" for s in completed)
    response = client.complete(
        system="Summarize the completed subtasks into one clear answer to the user's goal.",
        prompt=f"Goal: {task.goal}\n\nSubtask results:\n{context}",
    )
    return response.text
