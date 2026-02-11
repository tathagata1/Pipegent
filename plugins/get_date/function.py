from datetime import datetime
from typing import Callable


def get_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def register() -> tuple[str, Callable]:
    return "get_date", get_date