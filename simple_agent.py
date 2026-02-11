import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List

from openai import OpenAI
from config import chatgpt_key

os.environ["OPENAI_API_KEY"] = chatgpt_key
client = OpenAI()

SYSTEM_PROMPT_TEMPLATE = """
You are a strict tool-using AI agent.

RULES:
1. Always respond ONLY with valid JSON that selects a tool:
   {"tool": "<tool_name>", "args": {...}}
   - Never output plain text outside the JSON.
   - Never explain your reasoning.

2. Available tools and required args:
{tools_block}

3. A tool call is mandatory for every response. If nothing else fits, call speech with the words you want to say.
"""


def load_plugins(plugins_dir: Path) -> tuple[Dict[str, Callable], List[Dict[str, Any]]]:
    tools: Dict[str, Callable] = {}
    manifests: List[Dict[str, Any]] = []

    if not plugins_dir.exists():
        return tools, manifests

    for plugin_dir in plugins_dir.iterdir():
        if not plugin_dir.is_dir():
            continue

        module_path = plugin_dir / "function.py"
        manifest_path = plugin_dir / "manifest.json"
        if not module_path.exists() or not manifest_path.exists():
            print(f"Plugin '{plugin_dir.name}' is missing required files.")
            continue

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(f"Plugin '{plugin_dir.name}' has invalid manifest: {exc}")
            continue

        name = manifest.get("name")
        description = manifest.get("description", "No description provided.")
        input_schema = manifest.get("input_schema")
        function_name = manifest.get("execution_function")

        if not isinstance(name, str) or not name:
            print(f"Plugin '{plugin_dir.name}' missing valid name in manifest.")
            continue
        if not isinstance(function_name, str) or not function_name:
            print(f"Plugin '{plugin_dir.name}' missing execution_function.")
            continue
        if not isinstance(input_schema, dict):
            input_schema = {"type": "object", "properties": {}}

        spec = importlib.util.spec_from_file_location(
            f"plugins.{plugin_dir.name}.function", module_path
        )
        if spec is None or spec.loader is None:
            print(f"Plugin '{plugin_dir.name}' could not build import spec.")
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)  # type: ignore[call-arg]
        except Exception as exc:
            print(f"Failed to load plugin '{plugin_dir.name}': {exc}")
            continue

        func = getattr(module, function_name, None)
        if not callable(func):
            print(f"Plugin '{plugin_dir.name}' execution function '{function_name}' is invalid.")
            continue

        tools[name] = func
        manifests.append(
            {
                "name": name,
                "description": description,
                "input_schema": input_schema,
            }
        )

    return tools, manifests


def build_system_prompt(tool_specs: List[Dict[str, Any]]) -> str:
    tool_lines: List[str] = []
    for spec in tool_specs:
        name = spec.get("name", "unknown_tool")
        description = spec.get("description", "No description provided.")
        schema = spec.get("input_schema", {})
        schema_json = json.dumps(schema, ensure_ascii=True)
        tool_lines.append(
            f"   - {name}: {description}\n     input_schema: {schema_json}"
        )

    if not tool_lines:
        fallback_schema = json.dumps(
            {"type": "object", "properties": {"comment": {"type": "string"}}, "required": ["comment"]},
            ensure_ascii=True,
        )
        tool_lines.append(
            f"   - speech(comment: str): Default speech output\n     input_schema: {fallback_schema}"
        )

    tools_block = "\n".join(tool_lines)
    return SYSTEM_PROMPT_TEMPLATE.replace("{tools_block}", tools_block)


TOOLS, TOOL_SPECS = load_plugins(Path(__file__).parent / "plugins")
SYSTEM_PROMPT = build_system_prompt(TOOL_SPECS)

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
