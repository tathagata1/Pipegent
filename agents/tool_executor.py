import json
import logging
from typing import Any, Callable, Dict

from openai import OpenAI

logger = logging.getLogger(__name__)


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
        logger.debug("Executor response: %s", content)
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
