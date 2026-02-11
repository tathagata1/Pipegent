import os
import shutil
from pathlib import Path

from openai import OpenAI

from agent import PlannerAgent, ToolExecutor
from config import (
    chatgpt_key,
    executor_model,
    executor_temperature,
    max_steps,
    planner_model,
    planner_temperature,
)
from plugin_manager import load_plugins
from prompt_builder import build_system_prompt


def create_agent() -> PlannerAgent:
    os.environ["OPENAI_API_KEY"] = chatgpt_key
    client = OpenAI()

    plugins_dir = Path(__file__).parent / "plugins"
    tools, tool_specs = load_plugins(plugins_dir)
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

    return PlannerAgent(
        client=client,
        executor=executor,
        tool_specs=tool_specs,
        planner_model=planner_model,
        planner_temperature=planner_temperature,
        max_steps=max_steps,
        temp_dir=temp_dir,
    )



def prepare_temp_dir(temp_dir: Path) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)
    for item in temp_dir.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


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
