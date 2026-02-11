import json
import secrets
from pathlib import Path
from typing import Any, Callable, Dict, List

from openai import OpenAI


class ToolExecutor:
    """Runs individual instructions by forcing the executor LLM to use tools."""

    def __init__(
        self,
        client: OpenAI,
        tools: Dict[str, Callable],
        system_prompt: str,
        model: str,
        temperature: float,
    ) -> None:
        self.client = client
        self.tools = tools
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature

    def execute(self, instruction: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": instruction},
        ]

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )

        content = response.choices[0].message.content.strip()
        print("Executor LLM Response:", content)
        messages.append({"role": "assistant", "content": content})

        try:
            tool_call = json.loads(content)
        except json.JSONDecodeError:
            return content

        if not isinstance(tool_call, dict) or "tool" not in tool_call:
            return content

        tool_name = tool_call["tool"]
        args = self._normalize_args(tool_call)

        if tool_name not in self.tools:
            return f"Unknown tool: {tool_name}"

        result = self.tools[tool_name](**args)

        if tool_name == "speech":
            return str(result)

        messages.append(
            {
                "role": "user",
                "content": f"Tool '{tool_name}' result: {result}",
            }
        )

        final_response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )

        final_content = final_response.choices[0].message.content.strip()
        print("Executor Final Response:", final_content)

        try:
            final_tool = json.loads(final_content)
        except json.JSONDecodeError:
            return final_content

        if not isinstance(final_tool, dict) or "tool" not in final_tool:
            return final_content

        final_tool_name = final_tool["tool"]
        final_args = self._normalize_args(final_tool)

        if final_tool_name not in self.tools:
            return f"Unknown tool: {final_tool_name}"

        try:
            return str(self.tools[final_tool_name](**final_args))
        except Exception as exc:
            return f"Final tool '{final_tool_name}' error: {exc}"

    @staticmethod
    def _normalize_args(payload: Dict[str, Any]) -> Dict[str, Any]:
        args = payload.get("args")
        if isinstance(args, dict):
            return args
        return {k: v for k, v in payload.items() if k != "tool"}


class PlannerAgent:
    PLAN_SYSTEM_PROMPT = (
        "You are Pipegent's planning LLM. Break user goals into an ordered list of "
        "concrete steps that a separate execution agent can follow. Produce strictly "
        "valid JSON that looks like {{\"steps\": [\"step description\", ...]}} and return "
        "only as many steps as are truly required (between 1 and {max_steps}). "
        "Skip filler actions like greetings, generic follow-up questions, or waiting "
        "unless the user explicitly requests them."
    )
    SUMMARY_SYSTEM_PROMPT = (
        "You are Pipegent's planning LLM. Given the original request and the outputs "
        "from each executed step, craft a final response for the user that cites the "
        "completed work."
    )

    def __init__(
        self,
        client: OpenAI,
        executor: ToolExecutor,
        tool_specs: List[Dict[str, Any]],
        planner_model: str,
        planner_temperature: float,
        max_steps: int,
        temp_dir: Path,
    ) -> None:
        self.client = client
        self.executor = executor
        self.tool_specs = tool_specs
        self.planner_model = planner_model
        self.planner_temperature = planner_temperature
        self.max_steps = max(1, max_steps)
        self.temp_dir = temp_dir

    def handle_request(self, user_request: str) -> str:
        created_files: List[Path] = []
        try:
            steps = self._plan_steps(user_request)
            if not steps:
                steps = [user_request]
            steps = steps[: self.max_steps]

            step_results: List[Dict[str, Any]] = []
            for index, step in enumerate(steps, start=1):
                instruction = self._build_executor_instruction(
                    user_request, step, index, step_results
                )
                result_text = self.executor.execute(instruction)
                file_path = self._write_temp_file(result_text)
                created_files.append(file_path)
                step_results.append(
                    {
                        "step": step,
                        "result": result_text,
                        "file_path": str(file_path),
                    }
                )

            return self._build_final_response(user_request, steps, step_results)
        except Exception as exc:
            return f"Planner error: {exc}"
        finally:
            self._cleanup_temp_files(created_files)

    def _plan_steps(self, user_request: str) -> List[str]:
        tool_lines = "\n".join(
            f"- {spec.get('name')}: {spec.get('description')}" for spec in self.tool_specs
        ) or "(No plugins available)"

        user_prompt = (
            f"User request:\n{user_request}\n\nAvailable tools:\n{tool_lines}\n\n"
            f"Create between 1 and {self.max_steps} ordered steps that the execution agent should perform. "
            "Only include essential actions that directly move the user toward their goal; "
            "omit pleasantries or generic follow-ups unless explicitly requested."
        )

        messages = [
            {
                "role": "system",
                "content": self.PLAN_SYSTEM_PROMPT.format(max_steps=self.max_steps),
            },
            {"role": "user", "content": user_prompt},
        ]

        response = self.client.chat.completions.create(
            model=self.planner_model,
            messages=messages,
            temperature=self.planner_temperature,
        )

        content = response.choices[0].message.content.strip()
        print("Planner Plan Response:", content)

        try:
            parsed = json.loads(content)
            steps = parsed.get("steps", [])
            if isinstance(steps, list):
                return [str(step) for step in steps if str(step).strip()]
        except json.JSONDecodeError:
            pass

        return [user_request]

    def _build_executor_instruction(
        self,
        user_request: str,
        step: str,
        index: int,
        prior_results: List[Dict[str, Any]],
    ) -> str:
        if prior_results:
            previous = "\n\n".join(
                f"Step {idx + 1}: {entry['step']}\nFile: {entry['file_path']}\nOutput preview: {entry['result'][:300]}"
                for idx, entry in enumerate(prior_results)
            )
        else:
            previous = "None yet."

        return (
            f"Original request:\n{user_request}\n\n"
            f"You are executing plan step #{index}: {step}.\n"
            f"Previous step outputs:\n{previous}\n\n"
            "Use the available tools to accomplish this step."
        )

    def _build_final_response(
        self,
        user_request: str,
        steps: List[str],
        results: List[Dict[str, Any]],
    ) -> str:
        payload = {
            "user_request": user_request,
            "steps": steps,
            "results": [
                {
                    "step": entry["step"],
                    "output": entry["result"],
                }
                for entry in results
            ],
        }

        messages = [
            {"role": "system", "content": self.SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Craft the final response for the user using this context:\n"
                    + json.dumps(payload, ensure_ascii=False)
                ),
            },
        ]

        response = self.client.chat.completions.create(
            model=self.planner_model,
            messages=messages,
            temperature=self.planner_temperature,
        )

        final_content = response.choices[0].message.content.strip()
        return final_content

    def _write_temp_file(self, data: str) -> Path:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        filename = secrets.token_hex(8) + ".txt"
        file_path = self.temp_dir / filename
        file_path.write_text(str(data), encoding="utf-8")
        return file_path

    def _cleanup_temp_files(self, files: List[Path]) -> None:
        for file_path in files:
            try:
                file_path.unlink()
            except FileNotFoundError:
                pass
        try:
            if self.temp_dir.exists() and not any(self.temp_dir.iterdir()):
                self.temp_dir.rmdir()
        except OSError:
            pass
