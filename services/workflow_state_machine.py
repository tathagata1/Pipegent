from typing import Dict, FrozenSet

from agents.workflow_models import WorkflowState


class InvalidStateTransition(ValueError):
    pass


class WorkflowStateMachine:
    TRANSITIONS: Dict[WorkflowState, FrozenSet[WorkflowState]] = {
        WorkflowState.UNDERSTANDING_INTENT: frozenset({
            WorkflowState.AWAITING_CLARIFICATION, WorkflowState.PLANNING,
            WorkflowState.BLOCKED, WorkflowState.FAILED, WorkflowState.CANCELLED,
        }),
        WorkflowState.AWAITING_CLARIFICATION: frozenset({
            WorkflowState.UNDERSTANDING_INTENT, WorkflowState.CANCELLED,
        }),
        WorkflowState.PLANNING: frozenset({
            WorkflowState.READY_TO_EXECUTE, WorkflowState.BLOCKED,
            WorkflowState.FAILED, WorkflowState.CANCELLED,
        }),
        WorkflowState.READY_TO_EXECUTE: frozenset({
            WorkflowState.EXECUTING_STEP, WorkflowState.COMPLETED,
            WorkflowState.BLOCKED, WorkflowState.FAILED, WorkflowState.CANCELLED,
        }),
        WorkflowState.EXECUTING_STEP: frozenset({
            WorkflowState.VALIDATING_STEP, WorkflowState.BLOCKED,
            WorkflowState.FAILED, WorkflowState.CANCELLED,
        }),
        WorkflowState.VALIDATING_STEP: frozenset({
            WorkflowState.READY_TO_EXECUTE, WorkflowState.EXECUTING_STEP,
            WorkflowState.REPLANNING, WorkflowState.COMPLETED,
            WorkflowState.BLOCKED, WorkflowState.FAILED, WorkflowState.CANCELLED,
        }),
        WorkflowState.REPLANNING: frozenset({
            WorkflowState.READY_TO_EXECUTE, WorkflowState.BLOCKED,
            WorkflowState.FAILED, WorkflowState.CANCELLED,
        }),
        WorkflowState.COMPLETED: frozenset(),
        WorkflowState.BLOCKED: frozenset(),
        WorkflowState.FAILED: frozenset(),
        WorkflowState.CANCELLED: frozenset(),
    }

    @classmethod
    def can_transition(cls, current: WorkflowState, target: WorkflowState) -> bool:
        return target in cls.TRANSITIONS[current]

    @classmethod
    def transition(cls, current: WorkflowState, target: WorkflowState) -> WorkflowState:
        if not cls.can_transition(current, target):
            raise InvalidStateTransition(f"Cannot transition from {current} to {target}")
        return target
