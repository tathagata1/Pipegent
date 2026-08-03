import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Thread
from time import perf_counter
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
from console_output import display_message
from agents import PlannerAgent, ToolExecutor
from prompts import build_system_prompt
from services import JsonPlanRepository, load_plugins
from services.observability import log_event
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
    level_name = os.getenv("PIPEGENT_LOG_LEVEL", "DEBUG").upper()
    file_level = getattr(logging, level_name, logging.DEBUG)
    try:
        max_bytes = max(0, int(os.getenv("PIPEGENT_LOG_MAX_BYTES", "10485760")))
        backup_count = max(0, int(os.getenv("PIPEGENT_LOG_BACKUP_COUNT", "3")))
    except ValueError:
        max_bytes, backup_count = 10485760, 3
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(file_level)
    handlers: List[logging.Handler] = [file_handler]
    if os.getenv("PIPEGENT_LOG_TO_CONSOLE", "false").lower() in {
        "1", "true", "yes", "on",
    }:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(file_level)
        handlers.append(console_handler)
    logging.basicConfig(
        level=file_level,
        format=(
            "%(asctime)s.%(msecs)03d [%(levelname)s] [%(threadName)s] "
            "%(name)s - %(message)s"
        ),
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _LOG_FILE = log_file
    log_event(
        logger, "logging.initialized", level=logging.INFO,
        log_file=str(log_file), file_level=logging.getLevelName(file_level),
        console_enabled=len(handlers) > 1, max_bytes=max_bytes,
        backup_count=backup_count,
        max_value_chars=os.getenv("PIPEGENT_LOG_MAX_VALUE_CHARS", "50000"),
    )
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
                reconcile_on_startup=False,
                initialise_on_startup=False,
            )
            def warm_embeddings() -> None:
                started = perf_counter()
                try:
                    embeddings.warm_up()
                    memory_service.prepare()
                    log_event(
                        logger, "memory.embeddings.ready", level=logging.INFO,
                        elapsed_ms=round((perf_counter() - started) * 1000, 2),
                        model=embedding_model,
                    )
                except Exception:
                    logger.exception("Background embedding warm-up failed")

            Thread(
                target=warm_embeddings, name="embedding-warmup", daemon=True,
            ).start()
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
    log_event(
        logger, "agent.configuration", planner_model=planner_model,
        planner_temperature=planner_temperature, executor_model=executor_model,
        executor_temperature=executor_temperature,
        executor_timeout_seconds=executor_timeout_seconds,
        max_steps=max_steps, max_replans=max_replans,
        memory_enabled=memory_service is not None,
        tools=[item.get("name") for item in tool_specs],
        executor_system_prompt_chars=len(system_prompt),
    )
    executor = ToolExecutor(
        client=client,
        tools=tools,
        system_prompt=system_prompt,
        model=executor_model,
        temperature=executor_temperature,
        timeout_seconds=executor_timeout_seconds,
        memory_service=memory_service,
    )

    workflow_dir = Path(__file__).parent / "data" / "workflows"
    repository = JsonPlanRepository(workflow_dir)

    agent = PlannerAgent(
        client=client,
        executor=executor,
        tool_specs=tool_specs,
        planner_model=planner_model,
        planner_temperature=planner_temperature,
        max_steps=max_steps,
        repository=repository,
        max_replans=max_replans,
        memory_service=memory_service,
    )
    logger.info("Agent initialized with %s tools.", len(tools))
    return agent


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
    log_file = configure_logging()
    print("Initializing Pipegent...")
    print(f"Detailed log: {log_file}")
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
        logger.info("Console request received characters=%s", len(user_input))
        log_event(logger, "console.user_input", content=user_input)
        try:
            reply = agent.handle_request(user_input)
        except Exception as exc:
            logger.exception("Unhandled request failure")
            reply = f"The task failed unexpectedly: {exc}"
        displayed_reply = display_message(reply)
        print("Agent:", displayed_reply)
        logger.info(
            "Console response produced raw_characters=%s displayed_characters=%s",
            len(reply), len(displayed_reply),
        )
        log_event(
            logger, "console.agent_response", raw_content=reply,
            displayed_content=displayed_reply,
        )


if __name__ == "__main__":
    main()
