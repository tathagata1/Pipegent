import configparser
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
