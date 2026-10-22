"""Data specialist: delegates to the read-only `db_query` tool.

The demo database (seeded by `scripts/seed_demo_db.py`) has `customers` and
`orders` tables; this specialist pulls a representative join so downstream
subtasks (typically the code specialist) have real rows to analyze.
"""
from __future__ import annotations

from app.models.schemas import Subtask, Task
from app.tools.registry import ToolCallResult, get_tool_registry

_DEFAULT_QUERY = """
SELECT o.id AS order_id, o.customer_id, o.amount, o.status, c.name AS customer_name
FROM orders o
JOIN customers c ON c.id = o.customer_id
ORDER BY o.id
LIMIT 20
""".strip()


def run(subtask: Subtask, task: Task) -> ToolCallResult:
    registry = get_tool_registry()
    return registry.call(
        "db_query",
        agent="data_specialist",
        task_id=task.id,
        sql=_DEFAULT_QUERY,
    )
