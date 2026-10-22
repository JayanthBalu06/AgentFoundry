from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import Task, TaskCreateRequest, TaskStatus
from app.persistence.store import get_store
from app.workers.tasks import run_task_workflow

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=Task)
def create_task(body: TaskCreateRequest) -> Task:
    task = Task(user_id=body.user_id, goal=body.goal, status=TaskStatus.PENDING)
    get_store().save_task(task)
    run_task_workflow.delay(task.id)
    return task


@router.get("", response_model=list[Task])
def list_tasks(user_id: str) -> list[Task]:
    return get_store().list_tasks_for_user(user_id)


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str) -> Task:
    task = get_store().get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.get("/{task_id}/approvals")
def get_task_approvals(task_id: str) -> list:
    store = get_store()
    if store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    return store.list_approvals_for_task(task_id)


@router.post("/{task_id}/escalate")
def escalate_task(task_id: str, note: str | None = None) -> dict:
    """Human-initiated TAKE_OVER: pause automated execution entirely."""
    from app.models.schemas import ApprovalLevel, ApprovalRequest, EscalationReason

    store = get_store()
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")

    approval = ApprovalRequest(
        task_id=task.id,
        level=ApprovalLevel.TAKE_OVER,
        reason=EscalationReason.USER_REQUESTED,
        summary=note or "User requested to take over this task.",
    )
    store.save_approval(approval)
    task.status = TaskStatus.AWAITING_APPROVAL
    store.save_task(task)
    return {"approval_id": approval.id, "task_id": task.id}
