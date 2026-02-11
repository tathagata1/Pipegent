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

        return f"{tool_name} result: {result}"

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
        "only as many steps as are truly required (between 1 and {max_steps}). Skip filler "
        "actions like greetings, generic follow-up questions, or waiting unless the user "
        "explicitly requests them. Each step must correspond to exactly one tool invocation "
        "or simple action?never describe loops or say 'repeat'; instead enumerate every "
        "iteration explicitly (e.g., four dice rolls = four separate steps). Mention the "
        "tool to call (e.g., roll_dice, calculator) in each step. When using roll_dice, "
        "state rolls=1 unless the user explicitly asks for a different value. Remember that the "
        "calculator tool accepts only two inputs; summing more than two numbers requires multiple "
        "calculator steps (each adding two values or partial totals). Refer to prior results by step "
        "number (e.g., 'use the value from step 1') instead of inventing variable names."
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
            "omit pleasantries or generic follow-ups unless explicitly requested. Each step must map to a single tool call. "
            "If the user needs repeated actions (e.g., roll four times), output four distinct steps, one per iteration. "
            "Remember calculator accepts exactly two inputs; create additional calculator steps to accumulate sums beyond two numbers, and refer to earlier outputs by step number (e.g., 'use step 1 result') rather than inventing new variables."
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

        planned_steps: List[str] = []
        try:
            parsed = json.loads(content)
            candidate_steps = parsed.get("steps", [])
            if isinstance(candidate_steps, list):
                for raw in candidate_steps:
                    text_step = str(raw).strip()
                    if not text_step:
                        continue
                    if self._is_filler_step(text_step):
                        continue
                    if not self._mentions_tool(text_step):
                        continue
                    planned_steps.append(text_step)
        except json.JSONDecodeError:
            pass

        if not planned_steps:
            planned_steps = [user_request]

        return planned_steps[: self.max_steps]

    def _mentions_tool(self, step: str) -> bool:
        lowered = step.lower()
        for spec in self.tool_specs:
            name = str(spec.get("name", "")).lower()
            if name and name in lowered:
                return True
        return False

    @staticmethod
    def _is_filler_step(step: str) -> bool:
        fillers = [
            "greet","hello","hi","thank","assist you today","offer further assistance","wait for","check in"
        ]
        lowered = step.lower()
        return any(keyword in lowered for keyword in fillers)

    def _build_executor_instruction(
        self,
        user_request: str,
        step: str,
        index: int,
        prior_results: List[Dict[str, Any]],
    ) -> str:
        if prior_results:
            sections = []
            for idx, entry in enumerate(prior_results):
                file_path = Path(entry["file_path"]) if entry.get("file_path") else None
                try:
                    file_contents = (
                        file_path.read_text(encoding="utf-8") if file_path else entry["result"]
                    )
                except OSError:
                    file_contents = entry["result"]
                preview = file_contents[:300]
                sections.append(
                    f"Step {idx + 1}: {entry['step']}\nFile: {entry['file_path']}\nOutput preview: {preview}"
                )
            previous = "\n\n".join(sections)
        else:
            previous = "None yet."

        return (
            f"Original request:\n{user_request}\n\n"
            f"You are executing plan step #{index}: {step}.\n"
            f"Previous step outputs:\n{previous}\n\n"
            "Use the available tools to accomplish this step. Execute it exactly once?do not loop or batch. "
            "Keep tool arguments singular (for example, leave roll_dice 'rolls' at 1 unless this step explicitly says otherwise)."
        )

    def _build_final_response(
        self,
        user_request: str,
        steps: List[str],
        results: List[Dict[str, Any]],
    ) -> str:
        summarized_results = []
        for entry in results:
            file_path = Path(entry["file_path"]) if entry.get("file_path") else None
            try:
                file_contents = (
                    file_path.read_text(encoding="utf-8") if file_path else entry["result"]
                )
            except OSError:
                file_contents = entry["result"]

            summarized_results.append(
                {
                    "step": entry["step"],
                    "output_preview": file_contents[:1000],
                }
            )

        payload = {
            "user_request": user_request,
            "steps": steps,
            "results": summarized_results,
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
