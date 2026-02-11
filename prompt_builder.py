import json
from typing import Any, Dict, List

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
