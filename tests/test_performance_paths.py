import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.planner import PlannerAgent
from agents.tool_executor import ExecutorAgent
from services.plan_repository import JsonPlanRepository


def response(content):
    message = SimpleNamespace(
        role="assistant", content=json.dumps(content), refusal=None, tool_calls=None,
    )
    return SimpleNamespace(
        id="response", created=1, model="test-model", usage=None,
        choices=[SimpleNamespace(index=0, finish_reason="stop", message=message)],
    )


class CountingCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return response(self.payload)


class PerformancePathTests(unittest.TestCase):
    def test_context_free_social_turn_uses_no_model_call(self):
        completions = CountingCompletions({})
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        with tempfile.TemporaryDirectory() as directory:
            planner = PlannerAgent(
                client, object(), [], "test-model", 0, 3,
                repository=JsonPlanRepository(Path(directory)),
            )

            answer = planner.handle_request("hello")

        self.assertEqual(answer, "Hello! How can I help?")
        self.assertEqual(completions.calls, 0)

    def test_combined_plan_executes_preselected_tool_with_one_model_call(self):
        payload = {
            "needs_clarification": False,
            "questions": [],
            "objective": "Calculate the age.",
            "assumptions": [],
            "constraints": [],
            "success_criteria": ["Age is calculated."],
            "decision_summary": "A birthdate was supplied.",
            "direct_response": None,
            "strategy": "Use the age tool once.",
            "steps": [{
                "id": "step-1",
                "sequence": 1,
                "title": "Calculated age",
                "description": "Calculate the supplied birthdate's age.",
                "expected_outcome": "An integer age.",
                "validation_criteria": ["Age is calculated."],
                "dependencies": [],
                "max_retries": 0,
                "tool": "age_calculator",
                "args": {"birthdate": "1989-10-29"},
            }],
        }
        completions = CountingCompletions(payload)
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        executor = ExecutorAgent(
            client, {"age_calculator": lambda birthdate: 36},
            "legacy executor prompt", "test-model", 0,
        )
        tool_specs = [{
            "name": "age_calculator",
            "description": "Calculate age.",
            "input_schema": {
                "type": "object",
                "properties": {"birthdate": {"type": "string"}},
                "required": ["birthdate"],
            },
        }]

        with tempfile.TemporaryDirectory() as directory:
            planner = PlannerAgent(
                client, executor, tool_specs, "test-model", 0, 3,
                repository=JsonPlanRepository(Path(directory)),
            )
            answer = planner.handle_request("How old am I if I was born 1989-10-29?")

        self.assertEqual(answer, "Calculated age: 36")
        self.assertEqual(completions.calls, 1)

    def test_context_deduplicates_repeated_turns(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonPlanRepository(Path(directory))
            planner = PlannerAgent(
                object(), object(), [], "test-model", 0, 3,
                repository=repository,
            )
            from agents.workflow_models import WorkflowRecord, WorkflowState, utc_now

            now = utc_now()
            repository.save(WorkflowRecord(
                id="previous", session_id="default", state=WorkflowState.COMPLETED,
                objective="age", created_at=now, updated_at=now,
                conversation=(
                    [{"role": "user", "content": "what is my age"}] * 12
                    + [{"role": "user", "content": "29 october 1989"}]
                ),
                final_response="You are 36 years old.",
            ))

            context = planner._recent_session_context("default")

        self.assertEqual(
            sum(item["content"] == "what is my age" for item in context), 1
        )
        self.assertLessEqual(len(context), 8)


if __name__ == "__main__":
    unittest.main()
