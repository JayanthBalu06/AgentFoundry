"""Human-in-the-loop escalation: when to stop and ask, and at what level.

Four approval levels, cheapest to most disruptive:
  NOTIFY         - fyi only; we log it but never block on it here.
  APPROVE_ACTION - a single risky subtask (e.g. code execution) needs a yes/no.
  APPROVE_PLAN   - the supervisor's whole subtask plan needs sign-off.
  TAKE_OVER      - a human takes the task over entirely (via POST /tasks/{id}/escalate).

Each `get_or_create_*` helper is idempotent: re-running the graph after a
restart finds the existing pending (or already-decided) ApprovalRequest
instead of spawning a duplicate one.
"""
from __future__ import annotations

from app.models.schemas import (
    ApprovalLevel,
    ApprovalRequest,
    EscalationReason,
    Subtask,
    Task,
)
from app.persistence.store import TaskStore


def get_or_create_plan_approval(store: TaskStore, task: Task) -> ApprovalRequest:
    existing = [a for a in store.list_approvals_for_task(task.id) if a.level == ApprovalLevel.APPROVE_PLAN]
    if existing:
        return existing[-1]
    approval = ApprovalRequest(
        task_id=task.id,
        level=ApprovalLevel.APPROVE_PLAN,
        reason=EscalationReason.LOW_PLAN_CONFIDENCE,
        summary=f"Plan confidence {task.plan_confidence:.2f} is below the approval threshold.",
        payload={"subtasks": [s.model_dump(mode="json") for s in task.subtasks]},
    )
    store.save_approval(approval)
    return approval


def get_or_create_subtask_approval(
    store: TaskStore,
    task: Task,
    subtask: Subtask,
    reason: EscalationReason,
    summary: str,
) -> ApprovalRequest:
    existing = [
        a
        for a in store.list_approvals_for_task(task.id)
        if a.subtask_id == subtask.id
        and a.level == ApprovalLevel.APPROVE_ACTION
        and a.reason == reason
        and not a.decided
    ]
    if existing:
        return existing[-1]
    approval = ApprovalRequest(
        task_id=task.id,
        subtask_id=subtask.id,
        level=ApprovalLevel.APPROVE_ACTION,
        reason=reason,
        summary=summary,
        payload={"subtask": subtask.model_dump(mode="json")},
    )
    store.save_approval(approval)
    return approval


def log_notification(store: TaskStore, task: Task, subtask: Subtask | None, summary: str) -> ApprovalRequest:
    """A NOTIFY-level record: informational only, created already-decided so it
    never blocks execution, but still shows up in the approval history/dashboard.
    """
    approval = ApprovalRequest(
        task_id=task.id,
        subtask_id=subtask.id if subtask else None,
        level=ApprovalLevel.NOTIFY,
        reason=EscalationReason.REPEATED_FAILURE,
        summary=summary,
        decided=True,
        approved=True,
    )
    store.save_approval(approval)
    return approval


def latest_decided_approval(
    store: TaskStore,
    task_id: str,
    *,
    subtask_id: str | None,
    level: ApprovalLevel,
    reason: EscalationReason | None = None,
) -> ApprovalRequest | None:
    matches = [
        a
        for a in store.list_approvals_for_task(task_id)
        if a.level == level and a.subtask_id == subtask_id and a.decided and (reason is None or a.reason == reason)
    ]
    return matches[-1] if matches else None


def latest_approval_for_subtask(
    store: TaskStore, task_id: str, subtask_id: str, level: ApprovalLevel
) -> ApprovalRequest | None:
    """Most recent approval for this subtask/level, decided or not — used to
    resolve a subtask sitting in AWAITING_APPROVAL after a human decides.
    """
    matches = [
        a
        for a in store.list_approvals_for_task(task_id)
        if a.level == level and a.subtask_id == subtask_id
    ]
    return sorted(matches, key=lambda a: a.created_at)[-1] if matches else None
