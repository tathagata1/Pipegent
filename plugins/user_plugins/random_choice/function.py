import random
from typing import List


def random_choice(options: List[str]) -> str:
    if not options:
        raise ValueError('options cannot be empty')
    return random.choice(options)
