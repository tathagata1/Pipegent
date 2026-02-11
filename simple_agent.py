import importlib.util
import json
import os
from pathlib import Path
from typing import Callable, Dict, List

from openai import OpenAI
from config import chatgpt_key

os.environ["OPENAI_API_KEY"] = chatgpt_key
client = OpenAI()

def load_plugins(plugins_dir: Path) -> Dict[str, Callable]:
    tools: Dict[str, Callable] = {}

    if not plugins_dir.exists():
        return tools

    for plugin_dir in plugins_dir.iterdir():
        if not plugin_dir.is_dir():
            continue

        module_path = plugin_dir / "function.py"
        if not module_path.exists():
            continue

        spec = importlib.util.spec_from_file_location(
            f"plugins.{plugin_dir.name}.function", module_path
        )
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[call-arg]
        except Exception as exc:
            print(f"Failed to load plugin '{plugin_dir.name}': {exc}")
            continue

        register = getattr(module, "register", None)
        if not callable(register):
            print(f"Plugin '{plugin_dir.name}' missing register()")
            continue

        try:
            name, func = register()
        except Exception as exc:
            print(f"Plugin '{plugin_dir.name}' register() error: {exc}")
            continue

        if not callable(func):
            print(f"Plugin '{plugin_dir.name}' register() must return callable")
            continue

        tools[name] = func

    return tools


TOOLS = load_plugins(Path(__file__).parent / "plugins")

# -------------------
# Agent Loop
# -------------------

SYSTEM_PROMPT = """
You are a strict tool-using AI agent.

RULES:
1. Always respond ONLY with valid JSON that selects a tool:
   {"tool": "<tool_name>", "args": {...}}
   - Never output plain text outside the JSON.
   - Never explain your reasoning.

2. Available tools and required args:
   - calculator(a: float, b: float, operation: "add"|"subtract"|"multiply"|"divide")
   - get_time()  # no args
   - get_date()  # no args
   - tell_joke()  # no args
   - coin_flip()  # no args
   - roll_dice(sides: int = 6, rolls: int = 1)
   - speech(comment: str)  # use for natural-language replies

3. A tool call is mandatory for every response. If nothing else fits, call speech with the words you want to say.
"""

CONVERSATION_HISTORY: List[Dict[str, str]] = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

def run_agent(user_input: str):
    CONVERSATION_HISTORY.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=CONVERSATION_HISTORY,
        temperature=0
    )

    content = response.choices[0].message.content.strip()
    print("LLM Response:", content)

    CONVERSATION_HISTORY.append({"role": "assistant", "content": content})

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

    if tool_name not in TOOLS:
        return f"Unknown tool: {tool_name}"

    result = TOOLS[tool_name](**args)

    if tool_name == "speech":
        CONVERSATION_HISTORY.append({"role": "assistant", "content": result})
        return result

    tool_result_message = {
        "role": "user",
        "content": f"Tool '{tool_name}' result: {result}"
    }
    CONVERSATION_HISTORY.append(tool_result_message)

    final_response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=CONVERSATION_HISTORY,
        temperature=0
    )

    final_content = final_response.choices[0].message.content.strip()
    print("LLM Final Response:", final_content)

    CONVERSATION_HISTORY.append({"role": "assistant", "content": final_content})

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

    if final_tool_name not in TOOLS:
        return f"Unknown tool: {final_tool_name}"

    try:
        return TOOLS[final_tool_name](**final_args)
    except Exception as exc:
        return f"Final tool '{final_tool_name}' error: {exc}"

# -------------------
# Run
# -------------------

if __name__ == "__main__":
    while True:
        user_input = input("\nYou: ")
        if user_input.strip().lower() in {"exit", "quit"}:
            break

        reply = run_agent(user_input)
        print("Agent:", reply)