import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from openai import OpenAI

from config import (
    chatgpt_key,
    executor_model,
    executor_temperature,
    max_steps,
    planner_model,
    planner_temperature,
)
from agents import PlannerAgent, ToolExecutor
from prompts import build_system_prompt
from services import load_plugins


def create_agent() -> PlannerAgent:
    os.environ["OPENAI_API_KEY"] = chatgpt_key
    client = OpenAI()

    base_plugins_dir = Path(__file__).parent / "plugins"
    plugin_dirs = [
        base_plugins_dir / "core_plugins",
        base_plugins_dir / "user_plugins",
    ]
    tools, tool_specs = _load_all_plugins(plugin_dirs)
    if not tools:
        raise RuntimeError("No plugins were loaded. Ensure manifest.json files are valid.")

    system_prompt = build_system_prompt(tool_specs)
    executor = ToolExecutor(
        client=client,
        tools=tools,
        system_prompt=system_prompt,
        model=executor_model,
        temperature=executor_temperature,
    )

    temp_dir = Path(__file__).parent / "tempstore"
    prepare_temp_dir(temp_dir)
    context_file = initialize_context_file(temp_dir)
    os.environ["PIPEGENT_CONTEXT_FILE"] = str(context_file)

    return PlannerAgent(
        client=client,
        executor=executor,
        tool_specs=tool_specs,
        planner_model=planner_model,
        planner_temperature=planner_temperature,
        max_steps=max_steps,
        temp_dir=temp_dir,
        context_file=context_file,
    )


def prepare_temp_dir(temp_dir: Path) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    for item in temp_dir.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def initialize_context_file(temp_dir: Path) -> Path:
    for existing in temp_dir.glob("context_history*.json"):
        existing.unlink(missing_ok=True)

    run_id = uuid.uuid4().hex
    context_file = temp_dir / f"context_history_{run_id}.json"
    context_file.write_text("[]", encoding="utf-8")
    return context_file


def _load_all_plugins(plugin_dirs: List[Path]) -> Tuple[Dict[str, Callable[..., Any]], List[Dict[str, Any]]]:
    aggregated_tools: Dict[str, Callable[..., Any]] = {}
    aggregated_specs: List[Dict[str, Any]] = []
    for directory in plugin_dirs:
        dir_tools, dir_specs = load_plugins(directory)
        for name, func in dir_tools.items():
            if name in aggregated_tools:
                raise RuntimeError(f"Duplicate plugin name detected: {name}")
            aggregated_tools[name] = func
        aggregated_specs.extend(dir_specs)
    return aggregated_tools, aggregated_specs


def main() -> None:
    agent = create_agent()

    while True:
        try:
            user_input = input("\nYou: ")
        except EOFError:
            break

        if user_input.strip().lower() in {"exit", "quit"}:
            break

        reply = agent.handle_request(user_input)
        print("Agent:", reply)


if __name__ == "__main__":
    main()
