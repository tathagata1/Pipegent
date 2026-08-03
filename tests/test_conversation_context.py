import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.planner import PlannerAgent
from agents.tool_executor import ExecutorAgent
from agents.workflow_models import (
    ClarificationExchange, WorkflowRecord, WorkflowState,
)
from services.plan_repository import JsonPlanRepository


def workflow(
    workflow_id, state, conversation, *, final_response=None, updated_at="2026-01-01T00:00:00+00:00",
):
    return WorkflowRecord(
        id=workflow_id, session_id="default", state=state,
        objective=conversation[-1]["content"], conversation=conversation,
        created_at=updated_at, updated_at=updated_at,
        final_response=final_response,
    )


class CapturingPlanner(PlannerAgent):
    def _drive(self, item):
        self.captured = item
        return "captured"


class ConversationContextTests(unittest.TestCase):
    def test_new_workflow_inherits_latest_completed_session_context(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonPlanRepository(Path(directory))
            repository.save(workflow(
                "previous", WorkflowState.COMPLETED,
                [
                    {"role": "user", "content": "what is my age"},
                    {"role": "user", "content": "29 october 1989"},
                ],
                final_response="Your age is 36 years.",
            ))
            planner = CapturingPlanner(
                object(), object(), [], "test-model", 0, 3, Path(directory),
                repository=repository,
            )

            planner.handle_request("what is my age")

            self.assertEqual(
                planner.captured.conversation[-1],
                {"role": "user", "content": "what is my age"},
            )
            self.assertIn(
                {"role": "user", "content": "29 october 1989"},
                planner.captured.conversation,
            )
            self.assertIn(
                {"role": "assistant", "content": "Your age is 36 years."},
                planner.captured.conversation,
            )

    def test_existing_clarification_workflow_is_enriched_before_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonPlanRepository(Path(directory))
            repository.save(workflow(
                "previous", WorkflowState.COMPLETED,
                [{"role": "user", "content": "29 october 1989"}],
                final_response="Your age is 36 years.",
            ))
            active = workflow(
                "active", WorkflowState.AWAITING_CLARIFICATION,
                [{"role": "user", "content": "what is my age"}],
                updated_at="2026-01-02T00:00:00+00:00",
            )
            active.clarification_history.append(ClarificationExchange(
                questions=["What is your date of birth?"], answer=None,
                asked_at="2026-01-02T00:00:00+00:00",
            ))
            repository.save(active)
            planner = CapturingPlanner(
                object(), object(), [], "test-model", 0, 3, Path(directory),
                repository=repository,
            )

            planner.handle_request("what is my age")

            self.assertIn(
                {"role": "user", "content": "29 october 1989"},
                planner.captured.conversation,
            )
            self.assertIn(
                {"role": "assistant", "content": "Your age is 36 years."},
                planner.captured.conversation,
            )
            self.assertEqual(
                planner.captured.state, WorkflowState.UNDERSTANDING_INTENT
            )

    def test_memory_is_retrieved_before_intent_clarification(self):
        order = []

        class MemoryService:
            context_builder = SimpleNamespace(
                build=lambda items: "Stored birthdate: 1989-10-29"
            )

            def execute(self, request):
                order.append("memory")
                return SimpleNamespace(
                    status="success",
                    retrieved=[SimpleNamespace(memory_id="birthdate-memory")],
                )

        class Completions:
            def create(self, **kwargs):
                order.append("intent")
                self.assertions(kwargs)
                content = json.dumps({
                    "needs_clarification": False, "questions": [],
                    "objective": "Calculate the user's age.", "assumptions": [],
                    "constraints": [], "success_criteria": [],
                    "decision_summary": "The stored birthdate supplies the input.",
                })
                message = SimpleNamespace(
                    role="assistant", content=content, refusal=None, tool_calls=None,
                )
                return SimpleNamespace(
                    id="response", created=1, model="test-model", usage=None,
                    choices=[SimpleNamespace(
                        index=0, finish_reason="stop", message=message,
                    )],
                )

            @staticmethod
            def assertions(kwargs):
                assert order == ["memory", "intent"]
                assert "Stored birthdate: 1989-10-29" in kwargs["messages"][-1]["content"]

        class IntentOnlyPlanner(PlannerAgent):
            def _drive(self, item):
                self._retrieve_memory(item)
                self._transition(item, WorkflowState.UNDERSTANDING_INTENT)
                self._understand(item)
                self.captured = item
                return "captured"

        with tempfile.TemporaryDirectory() as directory:
            memory_service = MemoryService()
            client = SimpleNamespace(
                chat=SimpleNamespace(completions=Completions())
            )
            executor = ExecutorAgent(
                client, {}, "system", "test-model", 0,
                memory_service=memory_service,
            )
            planner = IntentOnlyPlanner(
                client, executor, [], "test-model", 0, 3, Path(directory),
                repository=JsonPlanRepository(Path(directory) / "workflows"),
                memory_service=memory_service,
            )

            planner.handle_request("what is my age")

            self.assertEqual(order, ["memory", "intent"])
            self.assertEqual(planner.captured.state, WorkflowState.PLANNING)


if __name__ == "__main__":
    unittest.main()
