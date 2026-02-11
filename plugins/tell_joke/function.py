import random
from typing import Callable

_JOKES = [
    "Why did the scarecrow get promoted? He was outstanding in his field!",
    "I told my computer I needed a break, and it said no problem--it needed one too.",
    "Parallel lines have so much in common. It's a shame they'll never meet."
]

def tell_joke() -> str:
    return random.choice(_JOKES)


def register() -> tuple[str, Callable]:
    return "tell_joke", tell_joke