"""The Celery task that drives one task's LangGraph run.

Retries are automatic (exponential backoff with jitter) via `autoretry_for`.
Recovery after a failure never repeats finished work: `run_graph` reloads
the Task from the checkpoint store on every call and the graph's `step`
node only ever acts on subtasks that are not already COMPLETED.
"""
from __future__ import annotations

import logging

from app.orchestrator.graph import run_graph
from app.persistence.store import get_store
from app.workers.celery_app import celery_app

log = logging.getLogger("agentfoundry.worker")


@celery_app.task(
    bind=True,
    max_retries=5,
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=120,
    retry_jitter=True,
)
def run_task_workflow(self, task_id: str) -> str:
    store = get_store()
    task = store.get_task(task_id)
    if task is None:
        log.error("run_task_workflow: unknown task_id=%s", task_id)
        return "unknown_task"

    log.info("run_task_workflow: resuming task_id=%s attempt=%s", task_id, self.request.retries)
    task = run_graph(task)
    return task.status.value
