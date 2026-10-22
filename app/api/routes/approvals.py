"""The human-approval queue API: list pending approvals and decide them.

Deciding an APPROVE_PLAN/APPROVE_ACTION approval doesn't resume the graph in
place — it just records the decision and re-enqueues the Celery task, which
calls `run_graph` again; `step()` finds the now-decided approval and
proceeds from exactly where it paused.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from app.models.schemas import ApprovalDecision, ApprovalLevel, ApprovalRequest, TaskStatus
from app.persistence.store import get_store
from app.workers.tasks import run_task_workflow

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRequest])
def list_pending_approvals() -> list[ApprovalRequest]:
    return get_store().list_pending_approvals()


@router.get("/{approval_id}", response_model=ApprovalRequest)
def get_approval(approval_id: str) -> ApprovalRequest:
    approval = get_store().get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    return approval


@router.post("/{approval_id}/decide", response_model=ApprovalRequest)
def decide_approval(approval_id: str, decision: ApprovalDecision) -> ApprovalRequest:
    store = get_store()
    approval = store.get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="approval not found")
    if approval.decided:
        raise HTTPException(status_code=409, detail="approval already decided")

    task = store.get_task(approval.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    approval.decided = True
    approval.approved = decision.approved
    approval.reviewer_note = decision.note
    approval.decided_at = datetime.now(timezone.utc)
    store.save_approval(approval)

    if approval.level == ApprovalLevel.TAKE_OVER:
        final_result = (decision.edited_payload or {}).get("final_result")
        if decision.approved and final_result:
            task.final_result = final_result
            task.status = TaskStatus.COMPLETED
            store.save_task(task)
            return approval
        task.status = TaskStatus.RUNNING
        store.save_task(task)

    run_task_workflow.delay(task.id)
    return approval
