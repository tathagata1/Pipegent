from statistics import median
from typing import List


def median_calculator(numbers: List[float]) -> float:
    if not numbers:
        raise ValueError('numbers cannot be empty')
    return median(numbers)
