import pytest

from app.models.schemas import Subtask, SubtaskStatus, SpecialistType
from app.orchestrator.dag import (
    DAGValidationError,
    all_complete,
    get_ready_subtasks,
    is_blocked,
    validate_dag,
)


def _subtask(id_: str, depends_on: list[str] | None = None, status=SubtaskStatus.PENDING) -> Subtask:
    return Subtask(
        id=id_,
        title=id_,
        description=id_,
        specialist=SpecialistType.DATA,
        depends_on=depends_on or [],
        status=status,
    )


def test_validate_dag_rejects_unknown_dependency():
    subtasks = [_subtask("a", depends_on=["ghost"])]
    with pytest.raises(DAGValidationError):
        validate_dag(subtasks)


def test_validate_dag_rejects_cycle():
    subtasks = [_subtask("a", depends_on=["b"]), _subtask("b", depends_on=["a"])]
    with pytest.raises(DAGValidationError):
        validate_dag(subtasks)


def test_validate_dag_accepts_valid_chain():
    subtasks = [_subtask("a"), _subtask("b", depends_on=["a"]), _subtask("c", depends_on=["b"])]
    validate_dag(subtasks)  # should not raise


def test_ready_subtasks_respects_dependencies():
    a = _subtask("a", status=SubtaskStatus.COMPLETED)
    b = _subtask("b", depends_on=["a"])
    c = _subtask("c", depends_on=["b"])
    ready = get_ready_subtasks([a, b, c])
    assert [s.id for s in ready] == ["b"]


def test_completed_subtask_is_never_rescheduled():
    """The core checkpointing guarantee: once COMPLETED, a subtask never
    reappears as ready, even if re-evaluated after a simulated crash/retry.
    """
    a = _subtask("a", status=SubtaskStatus.COMPLETED)
    b = _subtask("b", depends_on=["a"], status=SubtaskStatus.COMPLETED)
    c = _subtask("c", depends_on=["b"])
    subtasks = [a, b, c]

    # Simulate a resume: re-run scheduling against the exact same list.
    ready_first = get_ready_subtasks(subtasks)
    ready_again = get_ready_subtasks(subtasks)

    assert [s.id for s in ready_first] == ["c"]
    assert ready_first == ready_again
    assert not all_complete(subtasks)


def test_is_blocked_when_dependency_failed_permanently():
    a = _subtask("a", status=SubtaskStatus.FAILED)
    b = _subtask("b", depends_on=["a"])
    assert is_blocked([a, b])


def test_not_blocked_while_something_is_in_flight():
    a = _subtask("a", status=SubtaskStatus.RUNNING)
    b = _subtask("b", depends_on=["a"])
    assert not is_blocked([a, b])
