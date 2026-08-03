import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from openai import OpenAI

from config import (
    chatgpt_key,
    executor_model,
    executor_temperature,
    executor_timeout_seconds,
    max_replans,
    max_steps,
    planner_model,
    planner_temperature,
    memory_enabled, qdrant_api_key, qdrant_collection_prefix, qdrant_url,
    embedding_model, embedding_device, embedding_batch_size,
    embedding_local_files_only,
    memory_max_context_items, memory_min_similarity, memory_auto_store_enabled,
)
from agents import PlannerAgent, ToolExecutor
from prompts import build_system_prompt
from services import JsonPlanRepository, load_plugins
from memory.embeddings import SentenceTransformerEmbeddingProvider
from memory.repository import MemoryRepository
from memory.retrieval import MemoryRetriever, RetrievalContextBuilder
from memory.service import MemoryService
from memory.tools import build_memory_tools
from memory.vector_store import QdrantVectorStore
from memory.domain import UserMemorySettings

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

    memory_service = None
    if memory_enabled:
        try:
            embeddings = SentenceTransformerEmbeddingProvider(
                embedding_model, embedding_device, embedding_batch_size,
                local_files_only=embedding_local_files_only,
            )
            # Fail or finish model loading before accepting user input. This keeps
            # the first ordinary question from blocking inside memory retrieval.
            embeddings.warm_up()
            memory_repository = MemoryRepository(
                Path(__file__).parent / "data" / "memory.sqlite3"
            )
            memory_repository.save_settings(
                "default", "default",
                UserMemorySettings(
                    automatic_storage_enabled=memory_auto_store_enabled
                ),
            )
            vector_store = QdrantVectorStore(
                qdrant_url, f"{qdrant_collection_prefix}_v1",
                embeddings.dimensions, qdrant_api_key,
            )
            memory_service = MemoryService(
                memory_repository, embeddings, vector_store,
                retriever=MemoryRetriever(
                    memory_repository, embeddings, vector_store,
                    min_similarity=memory_min_similarity,
                ),
                context_builder=RetrievalContextBuilder(
                    max_items=memory_max_context_items
                ),
            )
            memory_tools, memory_specs = build_memory_tools(
                memory_service, tenant_id="default", user_id="default"
            )
            tools.update(memory_tools)
            tool_specs.extend(memory_specs)
        except Exception:
            logger.exception(
                "Memory startup failed; agent will run without memory. "
                "Start Qdrant and verify the embedding model installation."
            )

    system_prompt = build_system_prompt(tool_specs)
    executor = ToolExecutor(
        client=client,
        tools=tools,
        system_prompt=system_prompt,
        model=executor_model,
        temperature=executor_temperature,
        timeout_seconds=executor_timeout_seconds,
        memory_service=memory_service,
    )

    temp_dir = Path(__file__).parent / "data" / "tempstore"
    prepare_temp_dir(temp_dir)
    workflow_dir = Path(__file__).parent / "data" / "workflows"
    repository = JsonPlanRepository(workflow_dir)

    agent = PlannerAgent(
        client=client,
        executor=executor,
        tool_specs=tool_specs,
        planner_model=planner_model,
        planner_temperature=planner_temperature,
        max_steps=max_steps,
        temp_dir=temp_dir,
        repository=repository,
        max_replans=max_replans,
        memory_service=memory_service,
    )
    logger.info("Agent initialized with %s tools.", len(tools))
    return agent


def prepare_temp_dir(temp_dir: Path) -> None:
    temp_dir.mkdir(parents=True, exist_ok=True)


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
    print("Initializing Pipegent...")
    agent = create_agent()

    while True:
        try:
            user_input = input("\nYou: ")
        except (EOFError, KeyboardInterrupt):
            logger.info("Console interrupt received, shutting down Pipegent.")
            print("\nShutting down Pipegent.")
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
