import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.planner import PlannerAgent
from agents.tool_executor import ExecutorAgent
from agents.workflow_models import (
    ClarificationExchange, ExecutionError, ExecutionEvidence, ExecutionPlan,
    ExecutionResultStatus,
    ExecutorStepRequest, ExecutorStepResult, PlanStatus, PlanStep, StepStatus,
    WorkflowRecord, WorkflowState, utc_now,
)
from services.plan_repository import JsonPlanRepository
from services.result_validator import ExecutionResultValidator
from services.workflow_state_machine import InvalidStateTransition, WorkflowStateMachine


def response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class FakeCompletions:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.contents:
            raise AssertionError("Unexpected model call")
        return response(self.contents.pop(0))


class FakeClient:
    def __init__(self, contents):
        self.chat = SimpleNamespace(completions=FakeCompletions(contents))


class ScriptedExecutor:
    def __init__(self, statuses=None, evidence=True):
        self.statuses = list(statuses or [ExecutionResultStatus.SUCCESS])
        self.evidence = evidence
        self.requests = []
        self.active = 0
        self.max_active = 0

    def execute_step(self, request):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.requests.append(request)
        status = self.statuses.pop(0) if self.statuses else ExecutionResultStatus.SUCCESS
        result = ExecutorStepResult(
            plan_id=request.plan_id, step_id=request.step_id, status=status,
            summary=status.value, output="done",
            evidence=(
                [ExecutionEvidence("test", "value output verified", "done")]
                if self.evidence else []
            ),
            errors=(
                [ExecutionError("retryable failure", True)]
                if status == ExecutionResultStatus.FAILED else []
            ),
        )
        self.active -= 1
        return result


INTENT = json.dumps({
    "needs_clarification": False, "questions": [], "objective": "do it",
    "assumptions": [], "constraints": [], "success_criteria": ["done"],
})
CLARIFY = json.dumps({
    "needs_clarification": True, "questions": ["Which file should I use?"],
    "objective": "process a file", "assumptions": [], "constraints": [],
    "success_criteria": [],
})


def plan(steps=1, retries=2):
    return json.dumps({"steps": [
        {
            "id": f"step-{index}", "sequence": index, "title": f"Step {index}",
            "description": f"run tool {index}", "expected_outcome": "value output",
            "validation_criteria": ["value verified"],
            "dependencies": [] if index == 1 else [f"step-{index - 1}"],
            "max_retries": retries,
        }
        for index in range(1, steps + 1)
    ]})


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def agent(self, model_outputs, executor=None, max_replans=3):
        return PlannerAgent(
            client=FakeClient(model_outputs),
            executor=executor or ScriptedExecutor(),
            tool_specs=[{"name": "test_tool", "description": "test"}],
            planner_model="fake", planner_temperature=0, max_steps=5,
            temp_dir=self.root, repository=JsonPlanRepository(self.root / "state"),
            max_replans=max_replans,
        )

    def latest(self, agent):
        files = list((self.root / "state").glob("*.json"))
        self.assertTrue(files)
        return agent.repository.get(files[0].stem)

    def test_01_clarification_when_essential_information_missing(self):
        agent = self.agent([CLARIFY])
        self.assertIn("Which file", agent.handle_request("process it"))
        self.assertEqual(self.latest(agent).state, WorkflowState.AWAITING_CLARIFICATION)

    def test_02_answered_context_is_not_asked_again(self):
        agent = self.agent([CLARIFY, INTENT, plan(), "Finished"])
        agent.handle_request("process it")
        self.assertEqual(agent.handle_request("report.csv"), "Finished")
        second_intent = agent.client.chat.completions.calls[1]["messages"][1]["content"]
        self.assertIn("report.csv", second_intent)
        self.assertEqual(len(self.latest(agent).clarification_history), 1)

    def test_03_structured_plan_created_after_sufficient_information(self):
        agent = self.agent([INTENT, plan(), "Finished"])
        agent.handle_request("do it")
        workflow = self.latest(agent)
        self.assertIsInstance(workflow.plan, ExecutionPlan)
        self.assertEqual(workflow.plan.steps[0].id, "step-1")

    def test_04_only_one_step_is_dispatched_at_a_time(self):
        executor = ScriptedExecutor([
            ExecutionResultStatus.SUCCESS, ExecutionResultStatus.SUCCESS
        ])
        agent = self.agent([INTENT, plan(2), "Finished"], executor)
        agent.handle_request("do two things")
        self.assertEqual(executor.max_active, 1)
        self.assertEqual([item.step_id for item in executor.requests], ["step-1", "step-2"])

    def test_05_successful_step_is_validated_and_completed(self):
        agent = self.agent([INTENT, plan(), "Finished"])
        agent.handle_request("do it")
        workflow = self.latest(agent)
        self.assertTrue(workflow.validation_decisions[-1].valid)
        self.assertEqual(workflow.plan.steps[0].status, StepStatus.COMPLETED)

    def test_06_success_without_evidence_fails_validation(self):
        validator = ExecutionResultValidator()
        step = PlanStep("s", 1, "t", "d", "o", ["artifact exists"])
        result = ExecutorStepResult(
            "p", "s", ExecutionResultStatus.SUCCESS, "claimed success"
        )
        decision = validator.validate(step, result)
        self.assertFalse(decision.valid)
        self.assertIn("without evidence", decision.reason)

    def test_07_retryable_failure_honours_retry_limit(self):
        executor = ScriptedExecutor(
            [ExecutionResultStatus.FAILED] * 3
        )
        agent = self.agent([
            INTENT, plan(retries=2),
            json.dumps({"reason": "still broken", "action": "fail", "steps": []}),
        ], executor)
        agent.handle_request("do it")
        self.assertEqual(len(executor.requests), 3)
        self.assertEqual(self.latest(agent).state, WorkflowState.FAILED)

    def test_08_non_retryable_failure_can_block(self):
        executor = ScriptedExecutor([ExecutionResultStatus.BLOCKED])
        agent = self.agent([
            INTENT, plan(),
            json.dumps({"reason": "credentials required", "action": "block", "steps": []}),
        ], executor)
        reply = agent.handle_request("do it")
        self.assertIn("credentials required", reply)
        self.assertEqual(self.latest(agent).state, WorkflowState.BLOCKED)

    def test_09_partial_success_triggers_planner_decision(self):
        executor = ScriptedExecutor([ExecutionResultStatus.PARTIAL_SUCCESS])
        agent = self.agent([
            INTENT, plan(),
            json.dumps({"reason": "optional portion unavailable", "action": "skip", "steps": []}),
            "Completed with limitation",
        ], executor)
        self.assertEqual(agent.handle_request("do it"), "Completed with limitation")
        workflow = self.latest(agent)
        self.assertEqual(workflow.replan_count, 1)
        self.assertEqual(workflow.plan.steps[0].status, StepStatus.SKIPPED)

    def test_10_new_information_can_modify_remaining_plan(self):
        executor = ScriptedExecutor([
            ExecutionResultStatus.SUCCESS, ExecutionResultStatus.BLOCKED,
            ExecutionResultStatus.SUCCESS,
        ])
        replacement = json.loads(plan())["steps"]
        replacement[0]["id"] = "step-corrective"
        agent = self.agent([
            INTENT, plan(2),
            json.dumps({"reason": "new dependency", "action": "insert", "steps": replacement}),
            "Finished revised work",
        ], executor)
        agent.handle_request("do it")
        ids = [item.id for item in self.latest(agent).plan.steps]
        self.assertIn("step-corrective", ids)

    def test_11_completed_steps_are_retained_during_replanning(self):
        executor = ScriptedExecutor([
            ExecutionResultStatus.SUCCESS, ExecutionResultStatus.BLOCKED,
            ExecutionResultStatus.SUCCESS,
        ])
        replacement = json.loads(plan())["steps"]
        replacement[0]["id"] = "replacement"
        agent = self.agent([
            INTENT, plan(2),
            json.dumps({"reason": "replace remaining", "action": "revise", "steps": replacement}),
            "Finished",
        ], executor)
        agent.handle_request("do it")
        workflow = self.latest(agent)
        self.assertEqual(workflow.plan.steps[0].id, "step-1")
        self.assertEqual(workflow.plan.steps[0].status, StepStatus.COMPLETED)
        self.assertTrue(workflow.plan.revision_history)

    def test_12_executor_has_no_user_communication_api(self):
        executor = ExecutorAgent(FakeClient([]), {}, "prompt", "fake", 0)
        self.assertFalse(hasattr(executor, "send_user_message"))
        self.assertFalse(hasattr(executor, "handle_request"))

    def test_13_workflow_resumes_from_persisted_clarification_state(self):
        repository = JsonPlanRepository(self.root / "state")
        now = utc_now()
        record = WorkflowRecord(
            id="resume", session_id="default",
            state=WorkflowState.AWAITING_CLARIFICATION, objective="do it",
            conversation=[{"role": "user", "content": "do it"}],
            created_at=now, updated_at=now,
            clarification_history=[ClarificationExchange(["Which file?"], None, now)],
        )
        repository.save(record)
        agent = PlannerAgent(
            FakeClient([INTENT, plan(), "Resumed"]), ScriptedExecutor(),
            [{"name": "test_tool"}], "fake", 0, 5, self.root,
            repository=repository,
        )
        self.assertEqual(agent.handle_request("input.csv"), "Resumed")
        self.assertEqual(repository.get("resume").state, WorkflowState.COMPLETED)

    def test_14_duplicate_execution_and_request_are_idempotent(self):
        calls = []
        executor = ExecutorAgent(
            FakeClient([json.dumps({"tool": "write", "args": {}})]),
            {"write": lambda: calls.append("write") or "ok"}, "prompt", "fake", 0,
        )
        request = ExecutorStepRequest(
            "p", "s", "objective", "write", "value output",
            ["value verified"], {}, [], "stable-key",
        )
        executor.execute_step(request)
        executor.execute_step(request)
        self.assertEqual(calls, ["write"])

        scripted = ScriptedExecutor()
        agent = self.agent([INTENT, plan(), "Finished"], scripted)
        self.assertEqual(
            agent.handle_request("do it", request_id="stable-request"), "Finished"
        )
        self.assertEqual(
            agent.handle_request("do it", request_id="stable-request"), "Finished"
        )
        self.assertEqual(len(scripted.requests), 1)

    def test_15_final_answer_only_after_completion(self):
        agent = self.agent([CLARIFY])
        agent.handle_request("process it")
        workflow = self.latest(agent)
        self.assertIsNone(workflow.final_response)
        self.assertNotEqual(workflow.state, WorkflowState.COMPLETED)

    def test_16_cancellation_stops_dispatch(self):
        agent = self.agent([CLARIFY])
        agent.handle_request("process it")
        self.assertTrue(agent.cancel())
        self.assertEqual(self.latest(agent).state, WorkflowState.CANCELLED)

    def test_17_state_machine_and_replan_limits_prevent_loops(self):
        with self.assertRaises(InvalidStateTransition):
            WorkflowStateMachine.transition(
                WorkflowState.COMPLETED, WorkflowState.EXECUTING_STEP
            )
        executor = ScriptedExecutor([ExecutionResultStatus.PARTIAL_SUCCESS])
        agent = self.agent([INTENT, plan()], executor, max_replans=0)
        reply = agent.handle_request("do it")
        self.assertIn("maximum re-plan limit", reply)
        self.assertEqual(self.latest(agent).state, WorkflowState.FAILED)


if __name__ == "__main__":
    unittest.main()
