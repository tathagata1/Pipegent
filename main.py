import os
from pathlib import Path

from openai import OpenAI

from agent import Agent
from config import agent_model, agent_temperature, chatgpt_key
from plugin_manager import load_plugins
from prompt_builder import build_system_prompt


def create_agent() -> Agent:
    os.environ["OPENAI_API_KEY"] = chatgpt_key
    client = OpenAI()

    plugins_dir = Path(__file__).parent / "plugins"
    tools, tool_specs = load_plugins(plugins_dir)
    if not tools:
        raise RuntimeError("No plugins were loaded. Ensure manifest.json files are valid.")

    system_prompt = build_system_prompt(tool_specs)
    return Agent(
        client=client,
        tools=tools,
        system_prompt=system_prompt,
        model=agent_model,
        temperature=agent_temperature,
    )


def main() -> None:
    agent = create_agent()

    while True:
        try:
            user_input = input("\nYou: ")
        except EOFError:
            break

        if user_input.strip().lower() in {"exit", "quit"}:
            break

        reply = agent.run(user_input)
        print("Agent:", reply)


if __name__ == "__main__":
    main()
