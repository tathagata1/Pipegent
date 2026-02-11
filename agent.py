import json
from typing import Callable, Dict, List

from openai import OpenAI


class Agent:
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
        self.model = model
        self.temperature = temperature
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]

    def run(self, user_input: str) -> str:
        self.history.append({"role": "user", "content": user_input})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
            temperature=self.temperature,
        )

        content = response.choices[0].message.content.strip()
        print("LLM Response:", content)

        self.history.append({"role": "assistant", "content": content})

        try:
            tool_call = json.loads(content)
        except json.JSONDecodeError:
            return content

        if not isinstance(tool_call, dict) or "tool" not in tool_call:
            return content

        tool_name = tool_call["tool"]
        args = tool_call.get("args")
        if not isinstance(args, dict):
            args = {k: v for k, v in tool_call.items() if k != "tool"}

        if tool_name not in self.tools:
            return f"Unknown tool: {tool_name}"

        result = self.tools[tool_name](**args)

        if tool_name == "speech":
            self.history.append({"role": "assistant", "content": result})
            return result

        tool_result_message = {
            "role": "user",
            "content": f"Tool '{tool_name}' result: {result}",
        }
        self.history.append(tool_result_message)

        final_response = self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
            temperature=self.temperature,
        )

        final_content = final_response.choices[0].message.content.strip()
        print("LLM Final Response:", final_content)

        self.history.append({"role": "assistant", "content": final_content})

        try:
            final_tool = json.loads(final_content)
        except json.JSONDecodeError:
            return final_content

        if not isinstance(final_tool, dict) or "tool" not in final_tool:
            return final_content

        final_tool_name = final_tool["tool"]
        final_args = final_tool.get("args")
        if not isinstance(final_args, dict):
            final_args = {k: v for k, v in final_tool.items() if k != "tool"}

        if final_tool_name not in self.tools:
            return f"Unknown tool: {final_tool_name}"

        try:
            return self.tools[final_tool_name](**final_args)
        except Exception as exc:
            return f"Final tool '{final_tool_name}' error: {exc}"
