import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, Dict

from openai import OpenAI

from agents.workflow_models import (
    ExecutionError, ExecutionEvidence, ExecutionResultStatus,
    ExecutorStepRequest, ExecutorStepResult,
)
from memory.domain import MemoryOperationRequest, MemoryOperationResult

logger = logging.getLogger(__name__)


class ExecutorAgent:
    """A one-step worker. It deliberately has no user-output capability."""

    def __init__(
        self, client: OpenAI, tools: Dict[str, Callable[..., Any]],
        system_prompt: str, model: str, temperature: float,
        timeout_seconds: float = 60.0, memory_service: Any = None,
    ) -> None:
        self.client = client
        self.tools = tools
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self._completed: Dict[str, ExecutorStepResult] = {}
        self.memory_service = memory_service

    def execute_memory_operation(
        self, request: MemoryOperationRequest,
    ) -> MemoryOperationResult:
        """Execute a bounded structured memory operation assigned by the Planner."""
        if self.memory_service is None:
            return MemoryOperationResult(
                request.operation_id, request.action, "failed",
                errors=[{"code": "MEMORY_UNAVAILABLE",
                         "message": "Memory service is not configured."}],
            )
        return self.memory_service.execute(request)

    def execute_step(self, request: ExecutorStepRequest) -> ExecutorStepResult:
        cached = self._completed.get(request.idempotency_key)
        if cached is not None:
            logger.info("Executor deduplicated plan_id=%s step_id=%s",
                        request.plan_id, request.step_id)
            return cached
        logger.info("Executor invocation plan_id=%s step_id=%s",
                    request.plan_id, request.step_id)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": json.dumps(request.__dict__)},
                ],
                temperature=self.temperature,
            )
            content = (response.choices[0].message.content or "").strip()
            tool_call = json.loads(content)
            if not isinstance(tool_call, dict) or not isinstance(tool_call.get("tool"), str):
                raise ValueError("Executor did not select a tool.")
            tool_name = tool_call["tool"]
            args = self._normalize_args(tool_call)
            if tool_name not in self.tools:
                raise KeyError(f"Unknown tool: {tool_name}")
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.tools[tool_name], **args)
            try:
                output = future.result(timeout=self.timeout_seconds)
            except FutureTimeout:
                future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                return self._failure(
                    request, "TOOL_TIMEOUT",
                    f"Tool exceeded {self.timeout_seconds:g} seconds.", True,
                )
            else:
                pool.shutdown(wait=True)
            result = ExecutorStepResult(
                plan_id=request.plan_id, step_id=request.step_id,
                status=ExecutionResultStatus.SUCCESS,
                summary=f"Executed {tool_name} for the assigned step.",
                output=output,
                evidence=[ExecutionEvidence(
                    type="tool_result",
                    description=(
                        f"{tool_name} produced the expected outcome: "
                        f"{request.expected_outcome}. Validation criteria: "
                        f"{'; '.join(request.validation_criteria)}"
                    ),
                    value=output,
                )],
                discovered_facts={"tool_used": tool_name},
            )
            self._completed[request.idempotency_key] = result
            logger.info("Executor result plan_id=%s step_id=%s status=%s",
                        request.plan_id, request.step_id, result.status.value)
            return result
        except json.JSONDecodeError as exc:
            return self._failure(request, "INVALID_EXECUTOR_JSON", str(exc), True)
        except (TypeError, ValueError, KeyError) as exc:
            return self._failure(request, "INVALID_TOOL_CALL", str(exc), False)
        except Exception as exc:
            logger.exception("Executor failure plan_id=%s step_id=%s",
                             request.plan_id, request.step_id)
            return self._failure(request, type(exc).__name__, str(exc), True)

    def execute(self, instruction: str) -> str:
        """Compatibility adapter for the original string API."""
        request = ExecutorStepRequest(
            plan_id="legacy", step_id="legacy-step", objective=instruction,
            instruction=instruction, expected_outcome="Complete the instruction",
            validation_criteria=[], relevant_context={}, constraints=[],
            idempotency_key=f"legacy:{hash(instruction)}",
        )
        result = self.execute_step(request)
        return str(result.output) if result.status == ExecutionResultStatus.SUCCESS else result.summary

    @staticmethod
    def _normalize_args(payload: Dict[str, Any]) -> Dict[str, Any]:
        args = payload.get("args")
        return args if isinstance(args, dict) else {
            key: value for key, value in payload.items() if key != "tool"
        }

    @staticmethod
    def _failure(
        request: ExecutorStepRequest, code: str, message: str, retryable: bool,
    ) -> ExecutorStepResult:
        return ExecutorStepResult(
            plan_id=request.plan_id, step_id=request.step_id,
            status=ExecutionResultStatus.FAILED, summary=message,
            errors=[ExecutionError(
                code=code, message=message, retryable=retryable
            )],
        )


ToolExecutor = ExecutorAgent
