import configparser
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.ini")

config = configparser.ConfigParser()
if not config.read(CONFIG_PATH):
    raise FileNotFoundError(f"Missing config file: {CONFIG_PATH}")

chatgpt_key = config["OPENAI"]["chatgpt_key"]
agent_model = config["AGENT"]["model"]
agent_temperature = config.getfloat("AGENT", "temperature", fallback=0.0)
