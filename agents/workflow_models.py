from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowState(str, Enum):
    UNDERSTANDING_INTENT = "UNDERSTANDING_INTENT"
    RETRIEVING_MEMORY = "RETRIEVING_MEMORY"
    VALIDATING_RETRIEVED_CONTEXT = "VALIDATING_RETRIEVED_CONTEXT"
    AWAITING_CLARIFICATION = "AWAITING_CLARIFICATION"
    PLANNING = "PLANNING"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    EXECUTING_STEP = "EXECUTING_STEP"
    VALIDATING_STEP = "VALIDATING_STEP"
    CONSIDERING_MEMORY_WRITE = "CONSIDERING_MEMORY_WRITE"
    REPLANNING = "REPLANNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class ExecutionResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class PlanStep:
    id: str
    sequence: int
    title: str
    description: str
    expected_outcome: str
    validation_criteria: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    retry_count: int = 0
    max_retries: int = 2
    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "PlanStep":
        value = dict(value)
        value["status"] = StepStatus(value.get("status", StepStatus.PENDING))
        return cls(**value)


@dataclass
class PlanRevision:
    revision: int
    reason: str
    changed_at: str
    steps_snapshot: List[Dict[str, Any]]


@dataclass
class ExecutionPlan:
    id: str
    objective: str
    assumptions: List[str]
    constraints: List[str]
    success_criteria: List[str]
    status: PlanStatus
    steps: List[PlanStep]
    created_at: str
    updated_at: str
    current_step_id: Optional[str] = None
    revision: int = 1
    revision_history: List[PlanRevision] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ExecutionPlan":
        value = dict(value)
        value["status"] = PlanStatus(value["status"])
        value["steps"] = [PlanStep.from_dict(item) for item in value.get("steps", [])]
        value["revision_history"] = [
            PlanRevision(**item) for item in value.get("revision_history", [])
        ]
        return cls(**value)


@dataclass
class ExecutorStepRequest:
    plan_id: str
    step_id: str
    objective: str
    instruction: str
    expected_outcome: str
    validation_criteria: List[str]
    relevant_context: Dict[str, Any]
    constraints: List[str]
    idempotency_key: str
    tool_name: Optional[str] = None
    tool_args: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionEvidence:
    type: str
    description: str
    value: Any = None

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ExecutionEvidence":
        return cls(**value)


@dataclass
class ExecutionError:
    message: str
    retryable: bool
    code: Optional[str] = None
    details: Any = None

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ExecutionError":
        return cls(**value)


@dataclass
class ExecutorStepResult:
    plan_id: str
    step_id: str
    status: ExecutionResultStatus
    summary: str
    output: Any = None
    evidence: List[ExecutionEvidence] = field(default_factory=list)
    errors: List[ExecutionError] = field(default_factory=list)
    discovered_facts: Dict[str, Any] = field(default_factory=dict)
    suggested_next_action: Optional[str] = None

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "ExecutorStepResult":
        value = dict(value)
        value["status"] = ExecutionResultStatus(value["status"])
        value["evidence"] = [
            ExecutionEvidence.from_dict(item) for item in value.get("evidence", [])
        ]
        value["errors"] = [
            ExecutionError.from_dict(item) for item in value.get("errors", [])
        ]
        return cls(**value)


@dataclass
class ValidationDecision:
    valid: bool
    reason: str
    checked_criteria: List[str] = field(default_factory=list)
    missing_criteria: List[str] = field(default_factory=list)
    plan_id: Optional[str] = None
    step_id: Optional[str] = None
    decided_at: Optional[str] = None


@dataclass
class ClarificationExchange:
    questions: List[str]
    answer: Optional[str]
    asked_at: str
    answered_at: Optional[str] = None


@dataclass
class WorkflowRecord:
    id: str
    session_id: str
    state: WorkflowState
    objective: str
    conversation: List[Dict[str, str]]
    created_at: str
    updated_at: str
    clarification_history: List[ClarificationExchange] = field(default_factory=list)
    plan: Optional[ExecutionPlan] = None
    executor_results: List[ExecutorStepResult] = field(default_factory=list)
    validation_decisions: List[ValidationDecision] = field(default_factory=list)
    errors: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    replan_count: int = 0
    max_replans: int = 3
    cancelled: bool = False
    final_response: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "WorkflowRecord":
        value = dict(value)
        value["state"] = WorkflowState(value["state"])
        value["clarification_history"] = [
            ClarificationExchange(**item)
            for item in value.get("clarification_history", [])
        ]
        if value.get("plan"):
            value["plan"] = ExecutionPlan.from_dict(value["plan"])
        value["executor_results"] = [
            ExecutorStepResult.from_dict(item)
            for item in value.get("executor_results", [])
        ]
        value["validation_decisions"] = [
            ValidationDecision(**item)
            for item in value.get("validation_decisions", [])
        ]
        return cls(**value)
