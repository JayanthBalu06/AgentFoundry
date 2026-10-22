from app.orchestrator.dag import validate_dag
from app.orchestrator.supervisor import _heuristic_plan


def test_heuristic_plan_produces_a_valid_dependency_chain():
    confidence, subtasks = _heuristic_plan("Summarize this week's orders")
    validate_dag(subtasks)  # no cycles, no dangling deps
    specialists = [s.specialist.value for s in subtasks]
    assert specialists == ["data", "code", "api"]
    assert subtasks[1].depends_on == [subtasks[0].id]
    assert subtasks[2].depends_on == [subtasks[1].id]
    assert 0.0 <= confidence <= 1.0


def test_sensitive_keywords_lower_plan_confidence():
    normal_confidence, _ = _heuristic_plan("summarize recent orders")
    sensitive_confidence, _ = _heuristic_plan("delete all production payment records")
    assert sensitive_confidence < normal_confidence
