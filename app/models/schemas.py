"""Shared pydantic models for tasks, subtasks, and the human-approval workflow."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id() -> str:
    return uuid.uuid4().hex[:12]


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    REVIEWING = "reviewing"
    FAILED = "failed"
    COMPLETED = "completed"


class SubtaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"


class SpecialistType(str, Enum):
    API = "api"
    DATA = "data"
    CODE = "code"


class ApprovalLevel(str, Enum):
    NOTIFY = "notify"            # fyi only, execution continues
    APPROVE_ACTION = "approve_action"   # a single tool call needs a human yes/no
    APPROVE_PLAN = "approve_plan"       # the supervisor's whole subtask plan needs sign-off
    TAKE_OVER = "take_over"             # hand the task to a human entirely


class EscalationReason(str, Enum):
    LOW_PLAN_CONFIDENCE = "low_plan_confidence"
    REPEATED_FAILURE = "repeated_failure"
    SENSITIVE_OPERATION = "sensitive_operation"
    LOW_REVIEW_SCORE = "low_review_score"
    USER_REQUESTED = "user_requested"


class Subtask(BaseModel):
    id: str = Field(default_factory=_id)
    title: str
    description: str
    specialist: SpecialistType
    depends_on: list[str] = Field(default_factory=list)
    status: SubtaskStatus = SubtaskStatus.PENDING
    attempts: int = 0
    result: dict | None = None
    review_score: float | None = None
    review_feedback: str | None = None
    error: str | None = None


class Task(BaseModel):
    id: str = Field(default_factory=_id)
    user_id: str
    goal: str
    status: TaskStatus = TaskStatus.PENDING
    plan_confidence: float | None = None
    subtasks: list[Subtask] = Field(default_factory=list)
    final_result: str | None = None
    total_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=_id)
    task_id: str
    subtask_id: str | None = None
    level: ApprovalLevel
    reason: EscalationReason
    summary: str
    payload: dict = Field(default_factory=dict)
    decided: bool = False
    approved: bool | None = None
    reviewer_note: str | None = None
    created_at: datetime = Field(default_factory=_now)
    decided_at: datetime | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = None
    edited_payload: dict | None = None


class TaskCreateRequest(BaseModel):
    user_id: str
    goal: str


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=_id)
    user_id: str
    task_id: str | None = None
    kind: str = "episodic"  # "episodic" | "preference"
    text: str
    importance: float = 0.5
    created_at: datetime = Field(default_factory=_now)
    last_accessed_at: datetime = Field(default_factory=_now)
