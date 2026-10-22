"""The LangGraph workflow: a single self-looping `step` node that re-derives
"what to do next" from the Task document on every iteration — planning,
dependency-DAG scheduling, specialist dispatch, review, and human-approval
gating all live here.

Why one node instead of many: the Task document (persisted in Redis via
`TaskStore`) is the real source of truth, not LangGraph's own in-memory
state. Every iteration saves the Task right before returning, so a crash or
a Celery retry resumes by reloading that document and asking "what's next?"
again — already-COMPLETED subtasks are never re-run. A human approval
decision (via the API) doesn't resume a suspended graph in place; it just
updates the Task/ApprovalRequest and lets the next `run_graph()` call pick
up where things left off.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.memory.long_term_memory import get_long_term_memory
from app.memory.working_memory import WorkingMemory
from app.models.schemas import (
    ApprovalLevel,
    EscalationReason,
    MemoryRecord,
    SpecialistType,
    SubtaskStatus,
    Task,
    TaskStatus,
)
from app.observability.tracing import traced_step
from app.orchestrator import dag, escalation
from app.orchestrator import reviewer as reviewer_mod
from app.orchestrator import supervisor as supervisor_mod
from app.orchestrator.specialists import api_agent, code_agent, data_agent
from app.orchestrator.state import GraphState
from app.persistence.store import get_store
from app.tools.registry import ToolCallResult

log = logging.getLogger("agentfoundry.graph")

_SPECIALISTS = {
    SpecialistType.API: api_agent.run,
    SpecialistType.DATA: data_agent.run,
    SpecialistType.CODE: code_agent.run,
}


def _finish(task: Task, stop_reason: str | None) -> dict:
    get_store().save_task(task)  # checkpoint: safe to crash/retry after this point
    return {"task": task, "stop_reason": stop_reason}


def _resolve_awaiting_subtask(task: Task, subtask) -> dict | None:
    """If `subtask` is sitting in AWAITING_APPROVAL, try to resolve it from a
    human decision. Returns a finished state dict if we handled it (either
    because it's still waiting, or we just unblocked/killed it), else None.
    """
    store = get_store()
    approval = escalation.latest_approval_for_subtask(store, task.id, subtask.id, ApprovalLevel.APPROVE_ACTION)
    if approval is None or not approval.decided:
        return _finish(task, "awaiting_approval")

    if approval.reason == EscalationReason.SENSITIVE_OPERATION:
        subtask.status = SubtaskStatus.PENDING if approval.approved else SubtaskStatus.FAILED
        if not approval.approved:
            subtask.error = f"action rejected by reviewer: {approval.reviewer_note or 'no reason given'}"
    else:  # REPEATED_FAILURE / LOW_REVIEW_SCORE: accept last result, or give up
        subtask.status = SubtaskStatus.COMPLETED if approval.approved else SubtaskStatus.FAILED
        if not approval.approved:
            subtask.error = subtask.error or "low-quality result rejected by human reviewer"

    task.status = TaskStatus.RUNNING
    return _finish(task, None)


def step(state: GraphState) -> dict:
    task = state["task"]
    settings = get_settings()
    store = get_store()

    # 1. Plan, if we haven't yet.
    if not task.subtasks:
        with traced_step("supervisor.plan", task_id=task.id, agent="supervisor"):
            task = supervisor_mod.plan(task)
        dag.validate_dag(task.subtasks)
        task.status = TaskStatus.PLANNING
        return _finish(task, None)

    # 2. Plan-confidence gate.
    if task.plan_confidence is not None and task.plan_confidence < settings.plan_confidence_threshold:
        decided = escalation.latest_decided_approval(
            store, task.id, subtask_id=None, level=ApprovalLevel.APPROVE_PLAN
        )
        if decided is None:
            escalation.get_or_create_plan_approval(store, task)
            task.status = TaskStatus.AWAITING_APPROVAL
            return _finish(task, "awaiting_approval")
        if not decided.approved:
            task.status = TaskStatus.FAILED
            task.final_result = f"Plan rejected by reviewer: {decided.reviewer_note or 'no reason given'}"
            return _finish(task, "blocked")
        # approved: fall through to normal scheduling

    # 3. Resume a subtask that's waiting on a human decision.
    awaiting = next((s for s in task.subtasks if s.status == SubtaskStatus.AWAITING_APPROVAL), None)
    if awaiting is not None:
        result = _resolve_awaiting_subtask(task, awaiting)
        if result is not None:
            return result

    # 4. Done?
    if dag.all_complete(task.subtasks):
        with traced_step("supervisor.synthesize", task_id=task.id, agent="supervisor"):
            task.final_result = supervisor_mod.synthesize(task)
        task.status = TaskStatus.COMPLETED
        get_long_term_memory().add(
            MemoryRecord(
                user_id=task.user_id,
                task_id=task.id,
                kind="episodic",
                text=f"Goal: {task.goal}\nOutcome: {task.final_result[:500]}",
                importance=0.7,
            )
        )
        return _finish(task, "completed")

    # 5. Stuck?
    ready = dag.get_ready_subtasks(task.subtasks)
    if not ready:
        task.status = TaskStatus.FAILED
        task.final_result = "No subtask is runnable and the plan is not complete (stuck DAG)."
        return _finish(task, "blocked")

    subtask = sorted(ready, key=lambda s: s.id)[0]

    # 6. Pre-execution sensitive-operation gate (code execution).
    if subtask.specialist == SpecialistType.CODE:
        decided = escalation.latest_decided_approval(
            store,
            task.id,
            subtask_id=subtask.id,
            level=ApprovalLevel.APPROVE_ACTION,
            reason=EscalationReason.SENSITIVE_OPERATION,
        )
        if decided is None:
            escalation.get_or_create_subtask_approval(
                store,
                task,
                subtask,
                EscalationReason.SENSITIVE_OPERATION,
                f"Subtask '{subtask.title}' runs sandboxed code and requires approval before execution.",
            )
            subtask.status = SubtaskStatus.AWAITING_APPROVAL
            task.status = TaskStatus.AWAITING_APPROVAL
            return _finish(task, "awaiting_approval")
        if not decided.approved:
            subtask.status = SubtaskStatus.FAILED
            subtask.error = f"action rejected by reviewer: {decided.reviewer_note or 'no reason given'}"
            return _finish(task, None)
        # approved: fall through to execute

    # 7. Execute.
    subtask.status = SubtaskStatus.RUNNING
    subtask.attempts += 1
    run_fn = _SPECIALISTS[subtask.specialist]
    with traced_step(
        "specialist.execute",
        task_id=task.id,
        agent=f"{subtask.specialist.value}_specialist",
        subtask_id=subtask.id,
        attempt=subtask.attempts,
    ):
        result = run_fn(subtask, task)

    wm = WorkingMemory(task.id)
    wm.append_event({"subtask_id": subtask.id, "attempt": subtask.attempts, "tool_ok": result.ok, "latency_ms": result.latency_ms})

    if result.ok:
        subtask.error = None
        subtask.result = result.output if isinstance(result.output, dict) else {"output": result.output}
    else:
        subtask.error = result.error
        subtask.result = None

    # 8. Review.
    pseudo_result = ToolCallResult(ok=result.ok, output=subtask.result, error=subtask.error)
    with traced_step("reviewer.validate", task_id=task.id, agent="reviewer", subtask_id=subtask.id):
        score, feedback = reviewer_mod.validate(subtask, task.goal, pseudo_result)
    subtask.review_score = score
    subtask.review_feedback = feedback

    # 9. Post-review decision.
    if score >= settings.review_score_threshold:
        subtask.status = SubtaskStatus.COMPLETED
        wm.append_event({"subtask_id": subtask.id, "completed": True, "score": score})
        return _finish(task, None)

    if subtask.attempts < settings.max_specialist_retries:
        escalation.log_notification(
            store, task, subtask,
            f"Subtask '{subtask.title}' scored {score:.2f} on attempt {subtask.attempts}; retrying.",
        )
        subtask.description = f"{subtask.description}\n\n[reviewer feedback from a previous attempt: {feedback}]"
        subtask.status = SubtaskStatus.PENDING
        return _finish(task, None)

    reason = EscalationReason.LOW_REVIEW_SCORE if result.ok else EscalationReason.REPEATED_FAILURE
    escalation.get_or_create_subtask_approval(
        store, task, subtask, reason,
        f"Subtask '{subtask.title}' failed review after {subtask.attempts} attempts "
        f"(last score {score:.2f}): {feedback}",
    )
    subtask.status = SubtaskStatus.AWAITING_APPROVAL
    task.status = TaskStatus.AWAITING_APPROVAL
    return _finish(task, "awaiting_approval")


def _route(state: GraphState) -> str:
    return END if state["stop_reason"] else "step"


_graph = StateGraph(GraphState)
_graph.add_node("step", step)
_graph.set_entry_point("step")
_graph.add_conditional_edges("step", _route, {"step": "step", END: END})
compiled_graph = _graph.compile()


def run_graph(task: Task) -> Task:
    final_state = compiled_graph.invoke({"task": task, "stop_reason": None}, config={"recursion_limit": 200})
    return final_state["task"]
