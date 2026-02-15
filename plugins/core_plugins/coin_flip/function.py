import random

_OPTIONS = ("heads", "tails")


def coin_flip() -> str:
    return random.choice(_OPTIONS)
