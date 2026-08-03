from __future__ import annotations

import json
import logging
import os
import uuid
import re
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from openai import OpenAI

from agents.tool_executor import ExecutorAgent
from console_output import display_message
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
from services.observability import log_event, logged_chat_completion
from memory.domain import (
    MemoryAction, MemoryCandidate, MemoryOperationRequest, MemoryScope, MemorySource,
    MemoryType,
)

logger = logging.getLogger(__name__)


class PlannerAgent:
    """User-facing facade and owner of the persisted two-agent workflow."""

    def __init__(
        self, client: OpenAI, executor: ExecutorAgent,
        tool_specs: List[Dict[str, Any]], planner_model: str,
        planner_temperature: float, max_steps: int,
        context_file: Optional[Path] = None,
        repository: Optional[JsonPlanRepository] = None,
        validator: Optional[ExecutionResultValidator] = None,
        max_replans: int = 3,
        memory_service: Any = None, tenant_id: str = "default",
        user_id: Optional[str] = "default", project_id: Optional[str] = None,
        agent_id: str = "planner",
    ) -> None:
        self.client = client
        self.executor = executor
        self.tool_specs = tool_specs
        self.planner_model = planner_model
        self.planner_temperature = planner_temperature
        self.max_steps = max(1, max_steps)
        self.context_file = context_file
        self.repository = repository or JsonPlanRepository(
            Path(__file__).resolve().parents[1] / "data" / "workflows"
        )
        self.validator = validator or ExecutionResultValidator()
        self.max_replans = max(0, max_replans)
        self.state_machine = WorkflowStateMachine()
        self.memory_service = memory_service
        self.tenant_id, self.user_id = tenant_id, user_id
        self.project_id, self.agent_id = project_id, agent_id
        self._memory_disabled_sessions = set()

    def handle_request(
        self, user_request: str, session_id: str = "default",
        request_id: Optional[str] = None,
    ) -> str:
        """Accept user input and run until clarification or a terminal state."""
        trace_id = uuid.uuid4().hex
        request_started = perf_counter()
        log_event(
            logger, "planner.request.received", level=logging.INFO,
            trace_id=trace_id, request_id=request_id, session_id=session_id,
            user_request_chars=len(user_request),
        )
        log_event(
            logger, "planner.request.content", trace_id=trace_id,
            session_id=session_id, user_request=user_request,
        )
        directed = self._handle_directed_memory(user_request, session_id)
        if directed is not None:
            log_event(
                logger, "planner.request.directed_memory", level=logging.INFO,
                trace_id=trace_id, session_id=session_id,
                response_chars=len(directed),
                elapsed_ms=round((perf_counter() - request_started) * 1000, 2),
            )
            log_event(
                logger, "planner.request.directed_memory.content",
                trace_id=trace_id, session_id=session_id, response=directed,
            )
            return directed
        workflow = self.repository.get(request_id) if request_id else None
        if workflow and workflow.state in {
            WorkflowState.COMPLETED, WorkflowState.BLOCKED,
            WorkflowState.FAILED, WorkflowState.CANCELLED,
        }:
            return workflow.final_response or self._drive(workflow)
        if workflow is None:
            workflow = self.repository.find_active_by_session(session_id)
        if workflow is None and request_id is None:
            local_response = self._handle_local_response(user_request)
            if local_response is not None:
                log_event(
                    logger, "planner.request.local_response", level=logging.INFO,
                    trace_id=trace_id, session_id=session_id,
                    elapsed_ms=round((perf_counter() - request_started) * 1000, 2),
                    response=local_response,
                )
                return local_response
        if workflow is not None:
            self._add_recent_session_context(workflow)
        if workflow and workflow.state == WorkflowState.AWAITING_CLARIFICATION:
            exchange = workflow.clarification_history[-1]
            exchange.answer = user_request
            exchange.answered_at = utc_now()
            workflow.conversation.append({"role": "user", "content": user_request})
            self._transition(
                workflow,
                WorkflowState.RETRIEVING_MEMORY
                if self.memory_service is not None
                else WorkflowState.UNDERSTANDING_INTENT,
            )
        elif workflow is None:
            conversation = self._recent_session_context(session_id)
            conversation.append({"role": "user", "content": user_request})
            workflow = WorkflowRecord(
                id=request_id or uuid.uuid4().hex, session_id=session_id,
                state=(
                    WorkflowState.RETRIEVING_MEMORY
                    if self.memory_service is not None
                    else WorkflowState.UNDERSTANDING_INTENT
                ),
                objective=user_request,
                conversation=conversation,
                created_at=utc_now(), updated_at=utc_now(),
                max_replans=self.max_replans,
            )
            self._save(workflow)
            log_event(
                logger, "workflow.created", level=logging.INFO,
                trace_id=trace_id, workflow_id=workflow.id,
                session_id=session_id, objective=workflow.objective,
            )
        else:
            # Additional input while active is relevant context, not a second workflow.
            workflow.conversation.append({"role": "user", "content": user_request})
            workflow.updated_at = utc_now()
            self._save(workflow)

        try:
            result = self._drive(workflow)
            log_event(
                logger, "planner.request.completed", level=logging.INFO,
                trace_id=trace_id, workflow_id=workflow.id,
                final_state=workflow.state, response_chars=len(result),
                elapsed_ms=round((perf_counter() - request_started) * 1000, 2),
            )
            log_event(
                logger, "planner.request.response", trace_id=trace_id,
                workflow_id=workflow.id, response=result,
            )
            return result
        except Exception as exc:
            logger.exception("Planner workflow failed workflow_id=%s", workflow.id)
            workflow.errors.append({
                "code": type(exc).__name__, "message": str(exc), "at": utc_now()
            })
            if self.state_machine.can_transition(workflow.state, WorkflowState.FAILED):
                self._transition(workflow, WorkflowState.FAILED)
            workflow.final_response = f"The task failed: {exc}"
            self._save(workflow)
            log_event(
                logger, "planner.request.failed", level=logging.ERROR,
                trace_id=trace_id, workflow_id=workflow.id,
                state=workflow.state, error_type=type(exc).__name__,
                error=str(exc),
                elapsed_ms=round((perf_counter() - request_started) * 1000, 2),
            )
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
            log_event(
                logger, "workflow.state.processing", workflow_id=workflow.id,
                state=workflow.state, plan_id=(workflow.plan.id if workflow.plan else None),
                current_step_id=(
                    workflow.plan.current_step_id if workflow.plan else None
                ),
            )
            if workflow.cancelled:
                self._transition(workflow, WorkflowState.CANCELLED)
                break
            if workflow.state == WorkflowState.UNDERSTANDING_INTENT:
                self._understand(workflow)
            elif workflow.state == WorkflowState.RETRIEVING_MEMORY:
                self._retrieve_memory(workflow)
            elif workflow.state == WorkflowState.VALIDATING_RETRIEVED_CONTEXT:
                self._transition(workflow, WorkflowState.UNDERSTANDING_INTENT)
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
        retrieved_memory = next((
            item.get("context", "") for item in reversed(workflow.errors)
            if item.get("kind") == "retrieved_memory"
        ), "")
        payload = self._planner_json(
            f"Analyse intent and create the executable plan in one pass. Create no more "
            f"than {self.max_steps} steps. Do not repeat answered questions.\n"
            + INTENT_SCHEMA + "\nStep schema:\n" + PLAN_SCHEMA,
            {
                "available_tools": self._tool_summary(),
                "retrieved_memory": retrieved_memory,
                "conversation": workflow.conversation,
            },
            purpose="understand_intent", workflow_id=workflow.id,
        )
        log_event(
            logger, "planner.intent.decision", workflow_id=workflow.id,
            decision=payload,
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
        direct_response = str(payload.get("direct_response") or "").strip()
        if direct_response:
            workflow.final_response = direct_response
            self._transition(workflow, WorkflowState.COMPLETED)
            return
        raw_steps = payload.get("steps", [])
        if raw_steps:
            self._apply_plan(workflow, payload, raw_steps)
            self._transition(workflow, WorkflowState.READY_TO_EXECUTE)
            return
        # Old/custom planner responses may still return intent only.
        self._transition(workflow, WorkflowState.PLANNING)

    def _retrieve_memory(self, workflow: WorkflowRecord) -> None:
        if workflow.session_id in self._memory_disabled_sessions:
            workflow.errors.append({"kind": "retrieved_memory", "context": "",
                                    "memory_ids": []})
            self._transition(workflow, WorkflowState.VALIDATING_RETRIEVED_CONTEXT)
            return
        request = MemoryOperationRequest(
            operation_id=uuid.uuid4().hex, action=MemoryAction.SEARCH,
            tenant_id=self.tenant_id, user_id=self.user_id, agent_id=self.agent_id,
            session_id=workflow.session_id, project_id=self.project_id,
            query=workflow.conversation[-1]["content"], top_k=8,
            filters={"scopes": [
                MemoryScope.USER.value, MemoryScope.SESSION.value,
                MemoryScope.PROJECT.value, MemoryScope.ORGANISATION.value,
                MemoryScope.KNOWLEDGE_BASE.value,
            ]},
        )
        result = self.executor.execute_memory_operation(request)
        context = (
            self.memory_service.context_builder.build(result.retrieved)
            if result.status == "success" else ""
        )
        log_event(
            logger, "planner.memory.retrieved", workflow_id=workflow.id,
            operation_id=request.operation_id, query=request.query,
            status=result.status, retrieved=result.retrieved,
            built_context=context,
        )
        workflow.errors = [
            item for item in workflow.errors if item.get("kind") != "retrieved_memory"
        ]
        workflow.errors.append({
            "kind": "retrieved_memory", "context": context,
            "memory_ids": [item.memory_id for item in result.retrieved],
        })
        self._transition(workflow, WorkflowState.VALIDATING_RETRIEVED_CONTEXT)

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
                "retrieved_memory": next((
                    item.get("context", "") for item in reversed(workflow.errors)
                    if item.get("kind") == "retrieved_memory"
                ), ""),
            },
            purpose="create_plan", workflow_id=workflow.id,
        )
        raw_steps = payload.get("steps", [])
        if not raw_steps:
            raise ValueError("Planner returned no executable steps.")
        self._apply_plan(workflow, payload, raw_steps)
        self._transition(workflow, WorkflowState.READY_TO_EXECUTE)

    def _apply_plan(
        self, workflow: WorkflowRecord, payload: Dict[str, Any],
        raw_steps: List[Dict[str, Any]],
    ) -> None:
        """Materialise a planner decision without another model round trip."""
        metadata = next(
            (item for item in reversed(workflow.errors)
             if item.get("kind") == "intent_metadata"), {}
        )
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
        log_event(
            logger, "planner.plan.created", workflow_id=workflow.id,
            plan=workflow.plan, raw_planner_decision=payload,
        )

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
        log_event(
            logger, "planner.step.selected", workflow_id=workflow.id,
            plan_id=plan.id, step=step,
        )
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
                tool_name=step.tool_name, tool_args=step.tool_args,
            )
            result = self.executor.execute_step(request)
            workflow.executor_results.append(result)
            log_event(
                logger, "planner.step.execution_received", workflow_id=workflow.id,
                plan_id=plan.id, step_id=step.id, request=request, result=result,
            )
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
        log_event(
            logger, "planner.step.validation", workflow_id=workflow.id,
            plan_id=plan.id, revision=plan.revision, step=step,
            executor_result=result, decision=decision,
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
        timeout_failure = any(error.code == "TOOL_TIMEOUT" for error in result.errors)
        retry_limit = min(step.max_retries, 1) if timeout_failure else step.max_retries
        if (retryable or result.status == ExecutionResultStatus.SUCCESS) and (
            step.retry_count < retry_limit
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
            latest = next((
                item for item in reversed(workflow.executor_results)
                if item.step_id == current.id
            ), None)
            last_error = (
                latest.errors[-1].message
                if latest is not None and latest.errors else
                (latest.summary if latest is not None else "No executable replacement was found.")
            )
            current.status = StepStatus.FAILED
            plan.status = PlanStatus.FAILED
            workflow.final_response = (
                f"The task could not be completed after {workflow.max_replans} re-plans. "
                f"Last error: {last_error}"
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
                "available_tools": self._tool_summary(),
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
            purpose="replan", workflow_id=workflow.id,
        )
        reason = str(payload.get("reason") or "Execution result required re-planning.")
        log_event(
            logger, "planner.replan.decision", workflow_id=workflow.id,
            plan_id=plan.id, revision=plan.revision,
            current_step_id=current.id, decision=payload,
        )
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
            known_tools = {
                str(item.get("name")) for item in self.tool_specs if item.get("name")
            }
            unavailable = sorted({
                item.tool_name for item in replacements
                if item.tool_name and item.tool_name not in known_tools
            })
            if unavailable:
                current.status = StepStatus.BLOCKED
                plan.status = PlanStatus.BLOCKED
                reason = "Re-plan selected unavailable tool(s): " + ", ".join(unavailable)
                workflow.blockers.append(reason)
                workflow.final_response = (
                    "The task is blocked because no available tool could complete the "
                    f"failed step. {reason}"
                )
                self._transition(workflow, WorkflowState.BLOCKED)
                return
            completed = [item for item in plan.steps if item.status == StepStatus.COMPLETED]
            if replacements:
                existing_ids = {item.id for item in completed}
                replacements = [item for item in replacements if item.id not in existing_ids]
                plan.steps = completed + replacements
                replacement_ids = {item.id for item in replacements}
                workflow.executor_results = [
                    item for item in workflow.executor_results
                    if item.step_id not in replacement_ids
                ]
            else:
                current.status = StepStatus.PENDING
                current.retry_count = 0
                workflow.executor_results = [
                    item for item in workflow.executor_results
                    if not (item.plan_id == plan.id and item.step_id == current.id)
                ]
        plan.current_step_id = None
        plan.updated_at = utc_now()
        self._transition(workflow, WorkflowState.READY_TO_EXECUTE)

    def _build_final_response(self, workflow: WorkflowRecord) -> str:
        plan = self._require_plan(workflow)
        if os.getenv("PIPEGENT_SYNTHESIZE_FINAL_RESPONSE", "false").casefold() not in {
            "1", "true", "yes", "on",
        }:
            final_response = self._format_results(plan, workflow.executor_results)
            log_event(
                logger, "planner.final_response.formatted", workflow_id=workflow.id,
                plan_id=plan.id, response=final_response,
            )
            return final_response
        response = logged_chat_completion(
            client=self.client, target=logger, component="planner",
            purpose="build_final_response", model=self.planner_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    "Write only the concise final user-facing answer as plain text. "
                    "Do not return JSON, labels, metadata, completed-output lists, or a "
                    "decision summary. Mention a limitation only when it materially affects "
                    "the answer. Do not expose internal messages.\n"
                    + json.dumps({
                        "objective": plan.objective,
                        "steps": [asdict(item) for item in plan.steps],
                        "results": [asdict(item) for item in workflow.executor_results],
                    }, default=str)
                )},
            ],
            temperature=self.planner_temperature,
            context={"workflow_id": workflow.id, "plan_id": plan.id},
        )
        final_response = (response.choices[0].message.content or "").strip()
        log_event(
            logger, "planner.final_response.built", workflow_id=workflow.id,
            plan_id=plan.id, response=final_response,
        )
        return final_response

    @staticmethod
    def _format_results(plan: ExecutionPlan, results: List[Any]) -> str:
        """Render tool outputs locally; model synthesis is optional, not mandatory."""
        by_step = {result.step_id: result for result in results}

        def render(value: Any) -> str:
            if isinstance(value, str):
                return value.strip()
            if value is None:
                return "Completed."
            if isinstance(value, (bool, int, float)):
                return str(value)
            if isinstance(value, dict):
                lines = []
                for key, item in value.items():
                    label = str(key).replace("_", " ").strip().capitalize()
                    rendered = (
                        json.dumps(item, ensure_ascii=False, default=str)
                        if isinstance(item, (dict, list)) else str(item)
                    )
                    lines.append(f"{label}: {rendered}")
                return "\n".join(lines)
            return json.dumps(value, ensure_ascii=False, default=str)

        sections = []
        for step in sorted(plan.steps, key=lambda item: item.sequence):
            result = by_step.get(step.id)
            if result is None:
                continue
            body = render(result.output if result.output is not None else result.summary)
            if len(plan.steps) == 1 and isinstance(result.output, (bool, int, float)):
                sections.append(f"{step.title}: {body}")
            elif len(plan.steps) == 1 or isinstance(result.output, str):
                sections.append(body)
            else:
                sections.append(f"{step.title}:\n{body}")
        return "\n\n".join(sections).strip() or "Completed."

    def _planner_json(
        self, instruction: str, payload: Dict[str, Any], *, purpose: str,
        workflow_id: str,
    ) -> Dict[str, Any]:
        response = logged_chat_completion(
            client=self.client, target=logger, component="planner",
            purpose=purpose, model=self.planner_model,
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": instruction + "\n" +
                 json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=self.planner_temperature,
            context={"workflow_id": workflow_id},
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            log_event(
                logger, "planner.json.invalid", level=logging.WARNING,
                workflow_id=workflow_id, purpose=purpose,
                raw_model_output=content, error=str(exc),
            )
            raise
        if not isinstance(parsed, dict):
            raise ValueError("Planner response must be a JSON object.")
        log_event(
            logger, "planner.json.parsed", workflow_id=workflow_id,
            purpose=purpose, parsed=parsed,
        )
        return parsed

    def _parse_steps(self, raw_steps: List[Dict[str, Any]]) -> List[PlanStep]:
        steps: List[PlanStep] = []
        for index, raw in enumerate(raw_steps, 1):
            step_id = str(raw.get("id") or f"step-{index}")
            raw_tool_args = raw.get("args", raw.get("tool_args", {}))
            raw_tool_name = raw.get("tool", raw.get("tool_name"))
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
                tool_name=(str(raw_tool_name).strip() if raw_tool_name else None),
                tool_args=(dict(raw_tool_args) if isinstance(raw_tool_args, dict) else {}),
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
        log_event(
            logger, "workflow.transition", workflow_id=workflow.id,
            plan_id=workflow.plan.id if workflow.plan else None,
            revision=workflow.plan.revision if workflow.plan else None,
            from_state=old, to_state=target,
            current_step_id=(workflow.plan.current_step_id if workflow.plan else None),
        )
        self._save(workflow)

    def _save(self, workflow: WorkflowRecord) -> None:
        workflow.updated_at = utc_now()
        self.repository.save(workflow)

    def _tool_summary(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": item.get("name"),
                "description": item.get("description"),
                "input_schema": self._compact_schema(item.get("input_schema", {})),
            }
            for item in self.tool_specs
            if item.get("name") != "speech"
        ]

    @classmethod
    def _compact_schema(cls, value: Any) -> Any:
        """Keep argument semantics while dropping nonessential schema metadata."""
        if isinstance(value, dict):
            return {
                key: (
                    item[:240] if key == "description" and isinstance(item, str)
                    else cls._compact_schema(item)
                )
                for key, item in value.items()
                if key not in {"title", "examples", "$schema"}
            }
        if isinstance(value, list):
            return [cls._compact_schema(item) for item in value]
        return value

    def _recent_session_context(
        self, session_id: str, *, exclude_workflow_id: Optional[str] = None,
        max_messages: int = 8, max_characters: int = 6000,
    ) -> List[Dict[str, str]]:
        """Carry successful conversation context across workflow boundaries."""
        finder = getattr(self.repository, "find_latest_completed_by_session", None)
        if not callable(finder):
            return []
        previous = finder(
            session_id, exclude_workflow_id=exclude_workflow_id
        )
        if previous is None:
            return []
        context = [
            {
                "role": item["role"],
                "content": (
                    display_message(item["content"])
                    if item["role"] == "assistant" else item["content"]
                ),
            }
            for item in previous.conversation
            if item.get("role") in {"user", "assistant"}
            and isinstance(item.get("content"), str)
        ]
        if previous.final_response:
            context.append({
                "role": "assistant",
                "content": display_message(previous.final_response),
            })
        # Completed workflows already contain context inherited from their
        # predecessor. Retain only unique recent turns so repeated questions
        # do not grow every subsequent model request.
        carried_reversed: List[Dict[str, str]] = []
        seen = set()
        used = 0
        for item in reversed(context):
            signature = (item["role"], item["content"].strip())
            if not signature[1] or signature in seen:
                continue
            item_size = len(signature[1])
            if carried_reversed and used + item_size > max_characters:
                continue
            seen.add(signature)
            carried_reversed.append({"role": signature[0], "content": signature[1]})
            used += item_size
            if len(carried_reversed) >= max(1, max_messages):
                break
        carried = list(reversed(carried_reversed))
        log_event(
            logger, "planner.session_context.loaded",
            session_id=session_id, source_workflow_id=previous.id,
            message_count=len(carried), context=carried,
        )
        return carried

    @staticmethod
    def _handle_local_response(text: str) -> Optional[str]:
        """Answer context-free social turns without starting a workflow."""
        stripped = text.strip()
        if re.fullmatch(r"(?is)(?:hi|hello|hey|good\s+(?:morning|afternoon|evening))[!. ]*", stripped):
            return "Hello! How can I help?"
        if re.fullmatch(r"(?is)(?:thanks|thank\s+you|cheers)[!. ]*", stripped):
            return "You're welcome."
        if re.fullmatch(r"(?is)(?:accept|accepted|ok|okay|got\s+it)[!. ]*", stripped):
            return "Got it."
        return None

    def _add_recent_session_context(self, workflow: WorkflowRecord) -> None:
        context = self._recent_session_context(
            workflow.session_id, exclude_workflow_id=workflow.id
        )
        if not context:
            return
        completion_marker = context[-1]
        if completion_marker in workflow.conversation:
            return
        workflow.conversation = context + workflow.conversation
        log_event(
            logger, "planner.session_context.attached",
            workflow_id=workflow.id, session_id=workflow.session_id,
            added_message_count=len(context),
        )

    def _handle_directed_memory(
        self, text: str, session_id: str,
    ) -> Optional[str]:
        """Deterministic high-authority memory controls; no LLM can bypass policy."""
        if self.memory_service is None:
            return None
        stripped = text.strip()
        if re.match(
            r"(?is)^(?:do not|don't|disable)\s+(?:use\s+)?memory"
            r"(?:\s+(?:for|in))?\s+(?:this\s+)?conversation[.!]?$",
            stripped,
        ) or re.match(r"(?is)^do not remember this conversation[.!]?$", stripped):
            self._memory_disabled_sessions.add(session_id)
            return "Memory storage and retrieval are disabled for this conversation."
        if session_id in self._memory_disabled_sessions and re.match(
            r"(?is)^(?:please\s+)?(?:remember|save|learn)\b", stripped
        ):
            return "Memory is disabled for this conversation, so I did not store that."
        stated_name = re.match(
            r"(?is)^(?:my name is|i am|i'm)\s+([^.!?]+)[.!?]*$", stripped
        )
        if stated_name and session_id not in self._memory_disabled_sessions:
            name = stated_name.group(1).strip()
            result = self.executor.execute_memory_operation(MemoryOperationRequest(
                operation_id=uuid.uuid4().hex, action=MemoryAction.CREATE,
                tenant_id=self.tenant_id, user_id=self.user_id, agent_id=self.agent_id,
                session_id=session_id, project_id=self.project_id,
                memory=MemoryCandidate(
                    content=f"My name is {name}.", proposed_type=MemoryType.USER_FACT,
                    proposed_scope=MemoryScope.USER, source=MemorySource.USER_EXPLICIT,
                    reason="User-provided profile fact.", confidence=1.0, importance=0.8,
                ), explicit_user_request=True,
                idempotency_key=(
                    f"profile:name:{self.tenant_id}:{self.user_id}:{name.casefold()}"
                ),
            ))
            if result.status in {"success", "partial_success"}:
                return f"Nice to meet you, {name}."
            return f"Nice to meet you, {name}."
        remember = re.match(
            r"(?is)^(?:please\s+)?(?:remember|save|learn)\s+(?:that\s+|this\s+)?(.+)$",
            stripped,
        )
        if remember:
            content = remember.group(1).strip().rstrip(".")
            lowered = content.casefold()
            memory_type = (
                MemoryType.USER_PREFERENCE
                if any(word in lowered for word in ("prefer", "preference"))
                else MemoryType.PROCEDURE if "procedure" in lowered
                else MemoryType.PROJECT_FACT if "project" in lowered
                else MemoryType.USER_FACT
            )
            scope = (
                MemoryScope.PROJECT if "project" in lowered and self.project_id
                else MemoryScope.USER
            )
            request = MemoryOperationRequest(
                operation_id=uuid.uuid4().hex, action=MemoryAction.CREATE,
                tenant_id=self.tenant_id, user_id=self.user_id, agent_id=self.agent_id,
                session_id=session_id, project_id=self.project_id,
                memory=MemoryCandidate(
                    content=content, proposed_type=memory_type, proposed_scope=scope,
                    source=MemorySource.USER_EXPLICIT,
                    reason="The user explicitly requested long-term storage.",
                    confidence=1.0, importance=0.8,
                ), explicit_user_request=True,
                idempotency_key=f"explicit:{self.tenant_id}:{self.user_id}:{content.casefold()}",
            )
            result = self.executor.execute_memory_operation(request)
            indexed = any(
                item.get("persisted") and item.get("indexed")
                for item in result.evidence
            )
            if result.status == "success" and (
                indexed or any(item.get("type") == "duplicate" for item in result.evidence)
            ):
                return "I’ll remember that."
            if result.status == "partial_success":
                return (
                    "I saved that, but retrieval indexing is pending; it will be retried."
                )
            reason = "; ".join(result.warnings) or (
                result.errors[0]["message"] if result.errors else "storage was rejected"
            )
            return f"I couldn’t remember that: {reason}"
        if re.match(r"(?is)^what do you remember\b", stripped):
            request = MemoryOperationRequest(
                operation_id=uuid.uuid4().hex, action=MemoryAction.LIST,
                tenant_id=self.tenant_id, user_id=self.user_id,
                session_id=session_id, project_id=self.project_id,
            )
            result = self.executor.execute_memory_operation(request)
            if not result.records:
                return "I don’t have any stored memories for this scope."
            return "Stored memories:\n" + "\n".join(
                f"- {item.content}" for item in result.records
            )
        if re.match(
            r"(?is)^(?:what(?:'s| is)|do you (?:know|remember)) my name[?.!]*$",
            stripped,
        ):
            result = self.executor.execute_memory_operation(MemoryOperationRequest(
                operation_id=uuid.uuid4().hex, action=MemoryAction.LIST,
                tenant_id=self.tenant_id, user_id=self.user_id,
                session_id=session_id, project_id=self.project_id,
            ))
            for record in reversed(result.records):
                match = re.search(
                    r"(?is)\bmy name\s*(?:is|=)\s*([^.!?]+)", record.content
                )
                if match:
                    return f"Your name is {match.group(1).strip()}."
            return "I don’t have your name stored yet."
        delete = re.match(
            r"(?is)^(?:forget|delete memory)\s+(?:memory\s+)?([0-9a-f]{32})$", stripped
        )
        if delete:
            result = self.executor.execute_memory_operation(MemoryOperationRequest(
                operation_id=uuid.uuid4().hex, action=MemoryAction.DELETE,
                tenant_id=self.tenant_id, user_id=self.user_id,
                session_id=session_id, project_id=self.project_id,
                memory_id=delete.group(1),
            ))
            return (
                "I deleted that memory." if result.status == "success"
                else "I couldn’t delete that memory."
            )
        return None

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
