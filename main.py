import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

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

logger = logging.getLogger(__name__)
_LOG_FILE: Optional[Path] = None


def configure_logging() -> Path:
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE

    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"pipegent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
        force=True,
    )
    logging.getLogger("openai").setLevel(logging.WARNING)
    _LOG_FILE = log_file
    logger.info("Logging initialized at %s", log_file)
    return log_file


def create_agent() -> PlannerAgent:
    log_file = configure_logging()
    logger.info("Creating agent with logs at %s", log_file)
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

    agent = PlannerAgent(
        client=client,
        executor=executor,
        tool_specs=tool_specs,
        planner_model=planner_model,
        planner_temperature=planner_temperature,
        max_steps=max_steps,
        temp_dir=temp_dir,
        context_file=context_file,
    )
    logger.info("Agent initialized with %s tools.", len(tools))
    return agent


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
    logger.info("Loaded %s plugins from %s directories.", len(aggregated_tools), len(plugin_dirs))
    return aggregated_tools, aggregated_specs


def main() -> None:
    configure_logging()
    agent = create_agent()

    while True:
        try:
            user_input = input("\nYou: ")
        except EOFError:
            logger.info("EOF received, shutting down Pipegent.")
            break

        if user_input.strip().lower() in {"exit", "quit"}:
            logger.info("Exit command received. Terminating.")
            break

        if not user_input.strip():
            continue

        print("thinking...")
        logger.info("User input: %s", user_input)
        reply = agent.handle_request(user_input)
        print("Agent:", reply)
        logger.info("Agent response: %s", reply)


if __name__ == "__main__":
    main()
