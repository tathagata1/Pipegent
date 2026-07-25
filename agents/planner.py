from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from agents.tool_executor import ExecutorAgent
from agents.workflow_models import (
    ClarificationExchange, ExecutionPlan, ExecutionResultStatus,
    ExecutorStepRequest, PlanRevision, PlanStatus, PlanStep, StepStatus,
    WorkflowRecord, WorkflowState, utc_now,
)
from prompts.planner_prompt import (
    INTENT_SCHEMA, PLAN_SCHEMA, PLANNER_SYSTEM_PROMPT, REPLAN_SCHEMA,
)
from services.plan_repository import JsonPlanRepository
from services.result_validator import ExecutionResultValidator
from services.workflow_state_machine import WorkflowStateMachine

logger = logging.getLogger(__name__)


class PlannerAgent:
    """User-facing facade and owner of the persisted two-agent workflow."""

    def __init__(
        self, client: OpenAI, executor: ExecutorAgent,
        tool_specs: List[Dict[str, Any]], planner_model: str,
        planner_temperature: float, max_steps: int, temp_dir: Path,
        context_file: Optional[Path] = None,
        repository: Optional[JsonPlanRepository] = None,
        validator: Optional[ExecutionResultValidator] = None,
        max_replans: int = 3,
    ) -> None:
        self.client = client
        self.executor = executor
        self.tool_specs = tool_specs
        self.planner_model = planner_model
        self.planner_temperature = planner_temperature
        self.max_steps = max(1, max_steps)
        self.temp_dir = temp_dir
        self.context_file = context_file
        self.repository = repository or JsonPlanRepository(temp_dir / "workflows")
        self.validator = validator or ExecutionResultValidator()
        self.max_replans = max(0, max_replans)
        self.state_machine = WorkflowStateMachine()

    def handle_request(
        self, user_request: str, session_id: str = "default",
        request_id: Optional[str] = None,
    ) -> str:
        """Accept user input and run until clarification or a terminal state."""
        workflow = self.repository.get(request_id) if request_id else None
        if workflow and workflow.state in {
            WorkflowState.COMPLETED, WorkflowState.BLOCKED,
            WorkflowState.FAILED, WorkflowState.CANCELLED,
        }:
            return workflow.final_response or self._drive(workflow)
        if workflow is None:
            workflow = self.repository.find_active_by_session(session_id)
        if workflow and workflow.state == WorkflowState.AWAITING_CLARIFICATION:
            exchange = workflow.clarification_history[-1]
            exchange.answer = user_request
            exchange.answered_at = utc_now()
            workflow.conversation.append({"role": "user", "content": user_request})
            self._transition(workflow, WorkflowState.UNDERSTANDING_INTENT)
        elif workflow is None:
            workflow = WorkflowRecord(
                id=request_id or uuid.uuid4().hex, session_id=session_id,
                state=WorkflowState.UNDERSTANDING_INTENT,
                objective=user_request,
                conversation=[{"role": "user", "content": user_request}],
                created_at=utc_now(), updated_at=utc_now(),
                max_replans=self.max_replans,
            )
            self._save(workflow)
        else:
            # Additional input while active is relevant context, not a second workflow.
            workflow.conversation.append({"role": "user", "content": user_request})
            workflow.updated_at = utc_now()
            self._save(workflow)

        try:
            return self._drive(workflow)
        except Exception as exc:
            logger.exception("Planner workflow failed workflow_id=%s", workflow.id)
            workflow.errors.append({
                "code": type(exc).__name__, "message": str(exc), "at": utc_now()
            })
            if self.state_machine.can_transition(workflow.state, WorkflowState.FAILED):
                self._transition(workflow, WorkflowState.FAILED)
            workflow.final_response = f"The task failed: {exc}"
            self._save(workflow)
            return workflow.final_response

    def cancel(self, session_id: str = "default") -> bool:
        workflow = self.repository.find_active_by_session(session_id)
        if workflow is None:
            return False
        workflow.cancelled = True
        if self.state_machine.can_transition(workflow.state, WorkflowState.CANCELLED):
            self._transition(workflow, WorkflowState.CANCELLED)
        workflow.final_response = "The task was cancelled. No further steps will be dispatched."
        self._save(workflow)
        return True

    def _drive(self, workflow: WorkflowRecord) -> str:
        while workflow.state not in {
            WorkflowState.AWAITING_CLARIFICATION, WorkflowState.COMPLETED,
            WorkflowState.BLOCKED, WorkflowState.FAILED, WorkflowState.CANCELLED,
        }:
            if workflow.cancelled:
                self._transition(workflow, WorkflowState.CANCELLED)
                break
            if workflow.state == WorkflowState.UNDERSTANDING_INTENT:
                self._understand(workflow)
            elif workflow.state == WorkflowState.PLANNING:
                self._create_plan(workflow)
            elif workflow.state == WorkflowState.READY_TO_EXECUTE:
                self._select_step(workflow)
            elif workflow.state == WorkflowState.EXECUTING_STEP:
                self._execute_current_step(workflow)
            elif workflow.state == WorkflowState.VALIDATING_STEP:
                self._validate_current_step(workflow)
            elif workflow.state == WorkflowState.REPLANNING:
                self._replan(workflow)
            else:
                raise RuntimeError(f"Unhandled workflow state: {workflow.state}")

        if workflow.state == WorkflowState.AWAITING_CLARIFICATION:
            questions = workflow.clarification_history[-1].questions
            return "\n".join(questions)
        if workflow.state == WorkflowState.COMPLETED:
            if not workflow.final_response:
                workflow.final_response = self._build_final_response(workflow)
                self._save(workflow)
            return workflow.final_response
        if workflow.state == WorkflowState.BLOCKED:
            return workflow.final_response or (
                "The task is blocked: " + "; ".join(workflow.blockers)
            )
        if workflow.state == WorkflowState.CANCELLED:
            return workflow.final_response or "The task was cancelled."
        return workflow.final_response or "The task failed before it could be completed."

    def _understand(self, workflow: WorkflowRecord) -> None:
        payload = self._planner_json(
            "Analyse intent using the full conversation. Do not repeat answered questions.\n"
            + INTENT_SCHEMA,
            {"conversation": workflow.conversation, "available_tools": self._tool_summary()},
        )
        workflow.objective = str(payload.get("objective") or workflow.objective)
        questions = [
            str(item).strip() for item in payload.get("questions", []) if str(item).strip()
        ]
        if payload.get("needs_clarification") and questions:
            workflow.clarification_history.append(
                ClarificationExchange(questions=questions, answer=None, asked_at=utc_now())
            )
            self._transition(workflow, WorkflowState.AWAITING_CLARIFICATION)
            return
        workflow.errors = [
            item for item in workflow.errors if item.get("kind") != "intent_metadata"
        ]
        workflow.errors.append({
            "kind": "intent_metadata",
            "assumptions": payload.get("assumptions", []),
            "constraints": payload.get("constraints", []),
            "success_criteria": payload.get("success_criteria", []),
        })
        self._transition(workflow, WorkflowState.PLANNING)

    def _create_plan(self, workflow: WorkflowRecord) -> None:
        metadata = next(
            (item for item in reversed(workflow.errors)
             if item.get("kind") == "intent_metadata"), {}
        )
        payload = self._planner_json(
            f"Create no more than {self.max_steps} steps.\n{PLAN_SCHEMA}",
            {
                "objective": workflow.objective,
                "conversation": workflow.conversation,
                "available_tools": self._tool_summary(),
                "constraints": metadata.get("constraints", []),
            },
        )
        raw_steps = payload.get("steps", [])
        if not raw_steps:
            raise ValueError("Planner returned no executable steps.")
        plan_id = uuid.uuid4().hex
        steps = self._parse_steps(raw_steps[:self.max_steps])
        now = utc_now()
        workflow.plan = ExecutionPlan(
            id=plan_id, objective=workflow.objective,
            assumptions=list(metadata.get("assumptions", [])),
            constraints=list(metadata.get("constraints", [])),
            success_criteria=list(metadata.get("success_criteria", [])),
            status=PlanStatus.ACTIVE, steps=steps, created_at=now, updated_at=now,
        )
        self._transition(workflow, WorkflowState.READY_TO_EXECUTE)

    def _select_step(self, workflow: WorkflowRecord) -> None:
        plan = self._require_plan(workflow)
        active = [step for step in plan.steps if step.status == StepStatus.IN_PROGRESS]
        if len(active) > 1:
            raise RuntimeError("Invariant violation: multiple active steps.")
        if active:
            plan.current_step_id = active[0].id
            self._transition(workflow, WorkflowState.EXECUTING_STEP)
            return
        pending = sorted(
            (step for step in plan.steps if step.status == StepStatus.PENDING),
            key=lambda item: item.sequence,
        )
        if not pending:
            plan.status = PlanStatus.COMPLETED
            self._transition(workflow, WorkflowState.COMPLETED)
            return
        completed = {
            step.id for step in plan.steps if step.status == StepStatus.COMPLETED
        }
        step = pending[0]
        if any(dependency not in completed for dependency in step.dependencies):
            workflow.blockers.append(f"Dependencies unavailable for {step.id}.")
            step.status = StepStatus.BLOCKED
            plan.status = PlanStatus.BLOCKED
            self._transition(workflow, WorkflowState.BLOCKED)
            return
        step.status = StepStatus.IN_PROGRESS
        plan.current_step_id = step.id
        plan.updated_at = utc_now()
        self._transition(workflow, WorkflowState.EXECUTING_STEP)

    def _execute_current_step(self, workflow: WorkflowRecord) -> None:
        plan = self._require_plan(workflow)
        step = self._current_step(plan)
        prior = next(
            (result for result in reversed(workflow.executor_results)
             if result.plan_id == plan.id and result.step_id == step.id), None
        )
        if prior is None:
            relevant = {
                result.step_id: {
                    "summary": result.summary,
                    "output": result.output,
                    "discovered_facts": result.discovered_facts,
                }
                for result in workflow.executor_results
                if result.step_id in step.dependencies
            }
            request = ExecutorStepRequest(
                plan_id=plan.id, step_id=step.id, objective=plan.objective,
                instruction=step.description, expected_outcome=step.expected_outcome,
                validation_criteria=step.validation_criteria,
                relevant_context=relevant, constraints=plan.constraints,
                idempotency_key=f"{workflow.id}:{plan.id}:{step.id}",
            )
            result = self.executor.execute_step(request)
            workflow.executor_results.append(result)
            self._save(workflow)
        self._transition(workflow, WorkflowState.VALIDATING_STEP)

    def _validate_current_step(self, workflow: WorkflowRecord) -> None:
        plan = self._require_plan(workflow)
        step = self._current_step(plan)
        result = next(
            item for item in reversed(workflow.executor_results)
            if item.plan_id == plan.id and item.step_id == step.id
        )
        decision = self.validator.validate(step, result)
        decision.plan_id = plan.id
        decision.step_id = step.id
        decision.decided_at = utc_now()
        workflow.validation_decisions.append(decision)
        logger.info(
            "Validation workflow_id=%s plan_id=%s revision=%s step_id=%s valid=%s",
            workflow.id, plan.id, plan.revision, step.id, decision.valid,
        )
        if decision.valid:
            step.status = StepStatus.COMPLETED
            plan.current_step_id = None
            if all(item.status in {StepStatus.COMPLETED, StepStatus.SKIPPED}
                   for item in plan.steps):
                plan.status = PlanStatus.COMPLETED
                self._transition(workflow, WorkflowState.COMPLETED)
            else:
                self._transition(workflow, WorkflowState.READY_TO_EXECUTE)
            return
        retryable = any(error.retryable for error in result.errors)
        if (retryable or result.status == ExecutionResultStatus.SUCCESS) and (
            step.retry_count < step.max_retries
        ):
            step.retry_count += 1
            workflow.executor_results = [
                item for item in workflow.executor_results
                if not (item.plan_id == plan.id and item.step_id == step.id)
            ]
            logger.info("Retry workflow_id=%s step_id=%s count=%s reason=%s",
                        workflow.id, step.id, step.retry_count, decision.reason)
            self._transition(workflow, WorkflowState.EXECUTING_STEP)
            return
        self._transition(workflow, WorkflowState.REPLANNING)

    def _replan(self, workflow: WorkflowRecord) -> None:
        plan = self._require_plan(workflow)
        if workflow.replan_count >= workflow.max_replans:
            current = self._current_step(plan)
            current.status = StepStatus.FAILED
            plan.status = PlanStatus.FAILED
            workflow.final_response = (
                "The task failed because the maximum re-plan limit was reached."
            )
            self._transition(workflow, WorkflowState.FAILED)
            return
        workflow.replan_count += 1
        current = self._current_step(plan)
        result = next(
            item for item in reversed(workflow.executor_results)
            if item.step_id == current.id
        )
        payload = self._planner_json(
            "Choose a safe response to the result. Preserve completed steps.\n"
            + REPLAN_SCHEMA,
            {
                "objective": plan.objective,
                "current_step": asdict(current),
                "result": asdict(result),
                "completed_steps": [
                    asdict(item) for item in plan.steps
                    if item.status == StepStatus.COMPLETED
                ],
                "remaining_steps": [
                    asdict(item) for item in plan.steps
                    if item.status != StepStatus.COMPLETED
                ],
            },
        )
        reason = str(payload.get("reason") or "Execution result required re-planning.")
        plan.revision_history.append(PlanRevision(
            revision=plan.revision, reason=reason, changed_at=utc_now(),
            steps_snapshot=[asdict(item) for item in plan.steps],
        ))
        plan.revision += 1
        action = payload.get("action")
        if action == "block":
            current.status = StepStatus.BLOCKED
            plan.status = PlanStatus.BLOCKED
            workflow.blockers.append(reason)
            workflow.final_response = f"The task is blocked: {reason}"
            self._transition(workflow, WorkflowState.BLOCKED)
            return
        if action == "fail":
            current.status = StepStatus.FAILED
            plan.status = PlanStatus.FAILED
            workflow.final_response = f"The task failed: {reason}"
            self._transition(workflow, WorkflowState.FAILED)
            return
        if action == "skip":
            current.status = StepStatus.SKIPPED
        else:
            replacements = self._parse_steps(payload.get("steps", []))
            completed = [item for item in plan.steps if item.status == StepStatus.COMPLETED]
            if replacements:
                existing_ids = {item.id for item in completed}
                replacements = [item for item in replacements if item.id not in existing_ids]
                plan.steps = completed + replacements
            else:
                current.status = StepStatus.PENDING
                current.retry_count = 0
        plan.current_step_id = None
        plan.updated_at = utc_now()
        self._transition(workflow, WorkflowState.READY_TO_EXECUTE)

    def _build_final_response(self, workflow: WorkflowRecord) -> str:
        plan = self._require_plan(workflow)
        response = self.client.chat.completions.create(
            model=self.planner_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    "Write the concise final user-facing answer. Mention completed outputs "
                    "and material skipped work or limitations. Do not expose internal messages.\n"
                    + json.dumps({
                        "objective": plan.objective,
                        "steps": [asdict(item) for item in plan.steps],
                        "results": [asdict(item) for item in workflow.executor_results],
                    }, default=str)
                )},
            ],
            temperature=self.planner_temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def _planner_json(self, instruction: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.planner_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": instruction + "\n" +
                 json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=self.planner_temperature,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Planner response must be a JSON object.")
        return parsed

    def _parse_steps(self, raw_steps: List[Dict[str, Any]]) -> List[PlanStep]:
        steps: List[PlanStep] = []
        for index, raw in enumerate(raw_steps, 1):
            step_id = str(raw.get("id") or f"step-{index}")
            steps.append(PlanStep(
                id=step_id, sequence=int(raw.get("sequence", index)),
                title=str(raw.get("title") or step_id),
                description=str(raw.get("description") or raw.get("title") or ""),
                expected_outcome=str(raw.get("expected_outcome") or "Step completed"),
                validation_criteria=[
                    str(item) for item in raw.get("validation_criteria", [])
                ],
                dependencies=[str(item) for item in raw.get("dependencies", [])],
                max_retries=max(0, int(raw.get("max_retries", 2))),
            ))
        return steps

    def _transition(self, workflow: WorkflowRecord, target: WorkflowState) -> None:
        old = workflow.state
        workflow.state = self.state_machine.transition(old, target)
        workflow.updated_at = utc_now()
        logger.info(
            "Workflow transition workflow_id=%s plan_id=%s revision=%s "
            "from=%s to=%s step_id=%s",
            workflow.id, workflow.plan.id if workflow.plan else None,
            workflow.plan.revision if workflow.plan else None,
            old.value, target.value,
            workflow.plan.current_step_id if workflow.plan else None,
        )
        self._save(workflow)

    def _save(self, workflow: WorkflowRecord) -> None:
        workflow.updated_at = utc_now()
        self.repository.save(workflow)

    def _tool_summary(self) -> List[Dict[str, Any]]:
        return [
            {"name": item.get("name"), "description": item.get("description")}
            for item in self.tool_specs
        ]

    @staticmethod
    def _require_plan(workflow: WorkflowRecord) -> ExecutionPlan:
        if workflow.plan is None:
            raise RuntimeError("Workflow has no plan.")
        return workflow.plan

    @staticmethod
    def _current_step(plan: ExecutionPlan) -> PlanStep:
        matches = [item for item in plan.steps if item.id == plan.current_step_id]
        if len(matches) != 1:
            raise RuntimeError("Plan does not have exactly one current step.")
        return matches[0]
