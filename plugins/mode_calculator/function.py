from statistics import multimode
from typing import List


def mode_calculator(numbers: List[float]) -> List[float]:
    if not numbers:
        raise ValueError('numbers cannot be empty')
    return multimode(numbers)
