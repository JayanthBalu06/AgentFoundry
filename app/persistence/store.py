"""Redis-backed persistence for tasks and approval requests.

A `Task` document carries per-subtask status/result, so re-saving it after every
subtask is itself a checkpoint: if a worker process dies and a retry picks the task
back up, it reloads this document and skips any subtask already COMPLETED instead
of re-running the whole plan. See `app.workers.tasks.run_task_workflow`.
"""
from __future__ import annotations

import redis

from app.config import get_settings
from app.models.schemas import ApprovalRequest, Task

_TASK_KEY = "task:{id}"
_USER_TASKS_KEY = "tasks:by_user:{user_id}"
_APPROVAL_KEY = "approval:{id}"
_PENDING_APPROVALS_KEY = "approvals:pending"
_TASK_APPROVALS_KEY = "approvals:by_task:{task_id}"


class TaskStore:
    def __init__(self, client: redis.Redis | None = None) -> None:
        settings = get_settings()
        self._r = client or redis.Redis.from_url(settings.redis_url, decode_responses=True)

    # ---- tasks ---------------------------------------------------------
    def save_task(self, task: Task) -> None:
        self._r.set(_TASK_KEY.format(id=task.id), task.model_dump_json())
        self._r.sadd(_USER_TASKS_KEY.format(user_id=task.user_id), task.id)

    def get_task(self, task_id: str) -> Task | None:
        raw = self._r.get(_TASK_KEY.format(id=task_id))
        return Task.model_validate_json(raw) if raw else None

    def list_tasks_for_user(self, user_id: str) -> list[Task]:
        ids = self._r.smembers(_USER_TASKS_KEY.format(user_id=user_id))
        tasks = [self.get_task(tid) for tid in ids]
        return sorted((t for t in tasks if t), key=lambda t: t.created_at, reverse=True)

    # ---- approvals ------------------------------------------------------
    def save_approval(self, approval: ApprovalRequest) -> None:
        self._r.set(_APPROVAL_KEY.format(id=approval.id), approval.model_dump_json())
        self._r.sadd(_TASK_APPROVALS_KEY.format(task_id=approval.task_id), approval.id)
        if approval.decided:
            self._r.srem(_PENDING_APPROVALS_KEY, approval.id)
        else:
            self._r.sadd(_PENDING_APPROVALS_KEY, approval.id)

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        raw = self._r.get(_APPROVAL_KEY.format(id=approval_id))
        return ApprovalRequest.model_validate_json(raw) if raw else None

    def list_pending_approvals(self) -> list[ApprovalRequest]:
        ids = self._r.smembers(_PENDING_APPROVALS_KEY)
        approvals = [self.get_approval(aid) for aid in ids]
        return sorted((a for a in approvals if a), key=lambda a: a.created_at)

    def list_approvals_for_task(self, task_id: str) -> list[ApprovalRequest]:
        ids = self._r.smembers(_TASK_APPROVALS_KEY.format(task_id=task_id))
        approvals = [self.get_approval(aid) for aid in ids]
        return sorted((a for a in approvals if a), key=lambda a: a.created_at)


_store: TaskStore | None = None


def get_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store
