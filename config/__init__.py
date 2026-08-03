import configparser
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.ini"


def _load_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    if not parser.read(path):
        raise FileNotFoundError(f"Missing config file: {path}")
    return parser


config = _load_config(CONFIG_PATH)

chatgpt_key = config["OPENAI"]["chatgpt_key"]

planner_model = config["PLANNER_LLM"]["model"]
planner_temperature = config.getfloat("PLANNER_LLM", "temperature", fallback=0.2)

executor_model = config["EXECUTER_LLM"]["model"]
executor_temperature = config.getfloat("EXECUTER_LLM", "temperature", fallback=0.0)

max_steps = config.getint("AGENT", "max_steps", fallback=5)
max_replans = config.getint("AGENT", "max_replans", fallback=3)
executor_timeout_seconds = config.getfloat(
    "AGENT", "executor_timeout_seconds", fallback=60.0
)

memory_enabled = os.getenv("MEMORY_ENABLED", "true").lower() in {"1", "true", "yes"}
memory_auto_store_enabled = os.getenv(
    "MEMORY_AUTO_STORE_ENABLED", "false"
).lower() in {"1", "true", "yes"}
qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
qdrant_collection_prefix = os.getenv("QDRANT_COLLECTION_PREFIX", "agent_memory")
embedding_model = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
embedding_device = os.getenv("EMBEDDING_DEVICE", "cpu")
embedding_batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
embedding_local_files_only = os.getenv(
    "EMBEDDING_LOCAL_FILES_ONLY", "true"
).lower() in {"1", "true", "yes"}
memory_default_top_k = int(os.getenv("MEMORY_DEFAULT_TOP_K", "8"))
memory_max_context_items = int(os.getenv("MEMORY_MAX_CONTEXT_ITEMS", "10"))
memory_min_similarity = float(os.getenv("MEMORY_MIN_SIMILARITY", "0.45"))
