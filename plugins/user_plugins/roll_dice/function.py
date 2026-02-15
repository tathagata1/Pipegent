import random


def roll_dice(sides: int = 6, rolls: int = 1) -> str:
    if sides < 2:
        raise ValueError("sides must be at least 2")
    if rolls < 1:
        raise ValueError("rolls must be at least 1")

    results = [str(random.randint(1, sides)) for _ in range(rolls)]
    return ", ".join(results)
