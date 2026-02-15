import random

def random_number(min_value: int = 0, max_value: int = 100) -> int:
    if min_value > max_value:
        raise ValueError("min_value cannot exceed max_value")
    return random.randint(min_value, max_value)
