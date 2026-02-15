import configparser
from pathlib import Path
from typing import Iterable, List

BASE_DIR = Path(__file__).resolve().parent
SYSTEM_CONFIG_PATH = BASE_DIR / "system.config.ini"
USER_CONFIG_PATH = BASE_DIR / "user.config.ini"


def _load_config(paths: Iterable[Path]) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    read_files: List[str] = parser.read([str(path) for path in paths])

    missing = [path for path in paths if str(path) not in read_files]
    if missing:
        missing_str = ", ".join(str(path) for path in missing)
        raise FileNotFoundError(f"Missing config file(s): {missing_str}")
    return parser


config = _load_config([SYSTEM_CONFIG_PATH, USER_CONFIG_PATH])

chatgpt_key = config["OPENAI"]["chatgpt_key"]

planner_model = config["PLANNER_LLM"]["model"]
planner_temperature = config.getfloat("PLANNER_LLM", "temperature", fallback=0.2)

executor_model = config["EXECUTER_LLM"]["model"]
executor_temperature = config.getfloat("EXECUTER_LLM", "temperature", fallback=0.0)

max_steps = config.getint("AGENT", "max_steps", fallback=5)
