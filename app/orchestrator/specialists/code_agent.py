"""Code specialist: generates a small analysis script and runs it through the
sandboxed `run_python` tool.

Upstream results (e.g. rows the data specialist fetched) are serialized as a
JSON literal and embedded directly in the generated script, since the
sandbox has no filesystem or network access to fetch them itself.
"""
from __future__ import annotations

import json

from app.models.schemas import Subtask, Task
from app.orchestrator.specialists.base import find_dependency_results
from app.tools.registry import ToolCallResult, get_tool_registry


def _build_script(upstream: dict) -> str:
    rows = []
    for result in upstream.values():
        if isinstance(result, dict) and isinstance(result.get("rows"), list):
            rows.extend(result["rows"])

    payload = json.dumps(rows)
    return f"""
import json

rows = json.loads('''{payload}''')
amounts = [r["amount"] for r in rows if isinstance(r.get("amount"), (int, float))]
result = {{
    "row_count": len(rows),
    "total_amount": sum(amounts),
    "average_amount": (sum(amounts) / len(amounts)) if amounts else 0,
}}
print(json.dumps(result))
""".strip()


def run(subtask: Subtask, task: Task) -> ToolCallResult:
    registry = get_tool_registry()
    upstream = find_dependency_results(subtask, task)
    script = _build_script(upstream)

    result = registry.call(
        "run_python",
        agent="code_specialist",
        task_id=task.id,
        code=script,
    )

    if result.ok and isinstance(result.output, dict) and result.output.get("ok"):
        stdout = (result.output.get("stdout") or "").strip().splitlines()
        if stdout:
            try:
                parsed = json.loads(stdout[-1])
                result.output = {**result.output, "parsed": parsed}
            except json.JSONDecodeError:
                pass
    return result
