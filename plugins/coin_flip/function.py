import random
from typing import Callable

_OPTIONS = ("heads", "tails")

def coin_flip() -> str:
    return random.choice(_OPTIONS)


def register() -> tuple[str, Callable]:
    return "coin_flip", coin_flip