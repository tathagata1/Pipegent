import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import asdict
from time import perf_counter
from typing import Any, Callable, Dict

from openai import OpenAI

from agents.workflow_models import (
    ExecutionError, ExecutionEvidence, ExecutionResultStatus,
    ExecutorStepRequest, ExecutorStepResult,
)
from memory.domain import MemoryOperationRequest, MemoryOperationResult
from services.observability import log_event, logged_chat_completion

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
        log_event(
            logger, "executor.memory.request", operation_id=request.operation_id,
            action=request.action, request=request,
        )
        if self.memory_service is None:
            result = MemoryOperationResult(
                request.operation_id, request.action, "failed",
                errors=[{"code": "MEMORY_UNAVAILABLE",
                         "message": "Memory service is not configured."}],
            )
        else:
            result = self.memory_service.execute(request)
        log_event(
            logger, "executor.memory.response", operation_id=request.operation_id,
            action=request.action, result=result,
        )
        return result

    def execute_step(self, request: ExecutorStepRequest) -> ExecutorStepResult:
        cached = self._completed.get(request.idempotency_key)
        if cached is not None:
            logger.info("Executor deduplicated plan_id=%s step_id=%s",
                        request.plan_id, request.step_id)
            log_event(
                logger, "executor.step.deduplicated", plan_id=request.plan_id,
                step_id=request.step_id, cached_result=cached,
            )
            return cached
        logger.info("Executor invocation plan_id=%s step_id=%s",
                    request.plan_id, request.step_id)
        log_event(
            logger, "executor.step.request", plan_id=request.plan_id,
            step_id=request.step_id, request=asdict(request),
        )
        step_started = perf_counter()
        try:
            if request.tool_name:
                tool_call = {
                    "tool": request.tool_name,
                    "args": dict(request.tool_args),
                    "reason": "Preselected by the planner.",
                }
                content = json.dumps(tool_call, ensure_ascii=False)
                log_event(
                    logger, "executor.tool.preselected", plan_id=request.plan_id,
                    step_id=request.step_id, tool=request.tool_name,
                    arguments=request.tool_args,
                )
            else:
                # Backward-compatible routing for persisted plans created before
                # planners began supplying a validated tool name and arguments.
                response = logged_chat_completion(
                    client=self.client, target=logger, component="executor",
                    purpose="select_tool", model=self.model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": json.dumps(request.__dict__)},
                    ],
                    temperature=self.temperature,
                    context={"plan_id": request.plan_id, "step_id": request.step_id},
                )
                content = (response.choices[0].message.content or "").strip()
                tool_call = json.loads(content)
            if not isinstance(tool_call, dict) or not isinstance(tool_call.get("tool"), str):
                raise ValueError("Executor did not select a tool.")
            tool_name = tool_call["tool"]
            args = self._normalize_args(tool_call)
            if tool_name not in self.tools:
                raise KeyError(f"Unknown tool: {tool_name}")
            log_event(
                logger, "tool.selected", plan_id=request.plan_id,
                step_id=request.step_id, tool=tool_name, arguments=args,
                raw_model_output=content,
            )
            tool_started = perf_counter()
            logger.info(
                "Tool starting plan_id=%s step_id=%s tool=%s",
                request.plan_id, request.step_id, tool_name,
            )
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.tools[tool_name], **args)
            call_timeout = self._effective_timeout(args, self.timeout_seconds)
            try:
                output = future.result(timeout=call_timeout)
            except FutureTimeout:
                future.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                elapsed_ms = round((perf_counter() - tool_started) * 1000, 2)
                log_event(
                    logger, "tool.timeout", level=logging.WARNING,
                    plan_id=request.plan_id, step_id=request.step_id,
                    tool=tool_name, arguments=args, elapsed_ms=elapsed_ms,
                    timeout_seconds=call_timeout,
                )
                return self._failure(
                    request, "TOOL_TIMEOUT",
                    f"Tool exceeded {call_timeout:g} seconds.", True,
                )
            else:
                pool.shutdown(wait=True)
            tool_elapsed_ms = round((perf_counter() - tool_started) * 1000, 2)
            log_event(
                logger, "tool.result", plan_id=request.plan_id,
                step_id=request.step_id, tool=tool_name, arguments=args,
                output=output, elapsed_ms=tool_elapsed_ms,
            )
            logger.info(
                "Tool completed plan_id=%s step_id=%s tool=%s elapsed_ms=%.2f",
                request.plan_id, request.step_id, tool_name, tool_elapsed_ms,
            )
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
            log_event(
                logger, "executor.step.result", plan_id=request.plan_id,
                step_id=request.step_id, result=result,
                elapsed_ms=round((perf_counter() - step_started) * 1000, 2),
            )
            return result
        except json.JSONDecodeError as exc:
            log_event(
                logger, "executor.step.invalid_json", level=logging.WARNING,
                plan_id=request.plan_id, step_id=request.step_id,
                error=str(exc), raw_model_output=locals().get("content"),
            )
            return self._failure(request, "INVALID_EXECUTOR_JSON", str(exc), True)
        except (TypeError, ValueError, KeyError) as exc:
            log_event(
                logger, "executor.step.invalid_tool_call", level=logging.WARNING,
                plan_id=request.plan_id, step_id=request.step_id,
                error_type=type(exc).__name__, error=str(exc),
                raw_model_output=locals().get("content"),
            )
            return self._failure(request, "INVALID_TOOL_CALL", str(exc), False)
        except Exception as exc:
            logger.exception("Executor failure plan_id=%s step_id=%s",
                             request.plan_id, request.step_id)
            log_event(
                logger, "executor.step.error", level=logging.ERROR,
                plan_id=request.plan_id, step_id=request.step_id,
                error_type=type(exc).__name__, error=str(exc),
                elapsed_ms=round((perf_counter() - step_started) * 1000, 2),
            )
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
    def _effective_timeout(args: Dict[str, Any], default: float = 60.0) -> float:
        configured = args.get("timeout")
        if isinstance(configured, (int, float)) and not isinstance(configured, bool):
            return min(default, max(1.0, float(configured) + 2.0))
        return default

    @staticmethod
    def _normalize_args(payload: Dict[str, Any]) -> Dict[str, Any]:
        args = payload.get("args")
        return args if isinstance(args, dict) else {
            key: value for key, value in payload.items()
            if key not in {"tool", "reason"}
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
