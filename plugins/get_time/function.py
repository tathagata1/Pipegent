from datetime import datetime
from typing import Callable


def get_time() -> str:
    return datetime.now().strftime("%H:%M:%S")


def register() -> tuple[str, Callable]:
    return "get_time", get_time