import fakeredis

from app.models.schemas import ApprovalLevel, ApprovalRequest, EscalationReason, Subtask, SpecialistType, Task
from app.persistence.store import TaskStore


def _store() -> TaskStore:
    return TaskStore(client=fakeredis.FakeRedis(decode_responses=True))


def test_task_roundtrips_through_redis():
    store = _store()
    subtask = Subtask(title="t", description="d", specialist=SpecialistType.DATA)
    task = Task(user_id="u1", goal="goal", subtasks=[subtask])

    store.save_task(task)
    loaded = store.get_task(task.id)

    assert loaded is not None
    assert loaded.id == task.id
    assert loaded.subtasks[0].title == "t"
    assert [t.id for t in store.list_tasks_for_user("u1")] == [task.id]


def test_pending_approvals_are_indexed_and_cleared_on_decision():
    store = _store()
    task = Task(user_id="u1", goal="goal")
    store.save_task(task)

    approval = ApprovalRequest(
        task_id=task.id,
        level=ApprovalLevel.APPROVE_PLAN,
        reason=EscalationReason.LOW_PLAN_CONFIDENCE,
        summary="low confidence",
    )
    store.save_approval(approval)
    assert approval.id in [a.id for a in store.list_pending_approvals()]

    approval.decided = True
    approval.approved = True
    store.save_approval(approval)
    assert approval.id not in [a.id for a in store.list_pending_approvals()]
