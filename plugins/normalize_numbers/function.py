from typing import List


def normalize_numbers(numbers: List[float]) -> List[float]:
    if not numbers:
        raise ValueError('numbers cannot be empty')
    minimum = min(numbers)
    maximum = max(numbers)
    if minimum == maximum:
        return [0.0 for _ in numbers]
    return [(value - minimum) / (maximum - minimum) for value in numbers]
