"""Reviewer agent: validates a specialist's output before the supervisor
accepts it. Returns a 0-1 score and feedback text; the graph routes low
scores back for a retry (with the feedback attached) or, past the retry
budget, escalates to a human.
"""
from __future__ import annotations

import json

from app.config import get_settings
from app.llm.client import get_llm_client
from app.models.schemas import SpecialistType, Subtask
from app.tools.registry import ToolCallResult

_SYSTEM_PROMPT = (
    "You are a strict reviewer for an AI agent's work. Given the task goal, the "
    "subtask it attempted, and its raw tool output, return ONLY a JSON object: "
    '{"score": <0..1 float>, "feedback": "<one sentence>"}. Score low if the tool '
    "call failed, returned empty/irrelevant data, or did not address the subtask."
)


def _heuristic_review(subtask: Subtask, result: ToolCallResult) -> tuple[float, str]:
    if not result.ok:
        return 0.0, f"tool call failed: {result.error}"

    output = result.output or {}
    if subtask.specialist == SpecialistType.API:
        ok = bool(isinstance(output, dict) and output.get("ok"))
        return (0.9, "API call succeeded") if ok else (0.3, f"API call returned non-success: {output}")

    if subtask.specialist == SpecialistType.DATA:
        rows = output.get("rows") if isinstance(output, dict) else None
        return (0.9, f"retrieved {len(rows)} rows") if rows else (0.35, "query returned no rows")

    if subtask.specialist == SpecialistType.CODE:
        ran_ok = bool(isinstance(output, dict) and output.get("ok"))
        has_parsed = bool(isinstance(output, dict) and "parsed" in output)
        if ran_ok and has_parsed:
            return 0.9, "script ran successfully and produced structured output"
        if ran_ok:
            return 0.6, "script ran but produced no parseable JSON result"
        return 0.2, f"sandboxed script failed: {output.get('stderr', '')[:200]}"

    return 0.5, "no heuristic available for this specialist type"


def validate(subtask: Subtask, goal: str, result: ToolCallResult) -> tuple[float, str]:
    settings = get_settings()
    if settings.llm_provider == "mock":
        return _heuristic_review(subtask, result)

    client = get_llm_client()
    prompt = (
        f"Task goal: {goal}\n"
        f"Subtask: {subtask.title} — {subtask.description}\n"
        f"Specialist: {subtask.specialist.value}\n"
        f"Tool result ok={result.ok} error={result.error}\n"
        f"Output: {json.dumps(result.output)[:2000]}"
    )
    try:
        response = client.complete(system=_SYSTEM_PROMPT, prompt=prompt)
        parsed = json.loads(response.text)
        return float(parsed["score"]), str(parsed["feedback"])
    except Exception:  # noqa: BLE001 - fall back rather than crash the graph
        return _heuristic_review(subtask, result)
