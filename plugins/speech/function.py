from typing import Callable


def speech(comment: str) -> str:
    return comment


def register() -> tuple[str, Callable]:
    return "speech", speech