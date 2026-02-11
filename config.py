import configparser
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.ini")

config = configparser.ConfigParser()
if not config.read(CONFIG_PATH):
    raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")

chatgpt_key = config["OPENAI"]["chatgpt_key"]

planner_model = config["PLANNER_LLM"]["model"]
planner_temperature = config.getfloat("PLANNER_LLM", "temperature", fallback=0.2)

executor_model = config["EXECUTER_LLM"]["model"]
executor_temperature = config.getfloat("EXECUTER_LLM", "temperature", fallback=0.0)

max_steps = config.getint("AGENT", "max_steps", fallback=5)
