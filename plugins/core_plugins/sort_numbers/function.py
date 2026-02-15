from typing import List


def sort_numbers(numbers: List[float], descending: bool = False) -> List[float]:
    if not numbers:
        return []
    return sorted(numbers, reverse=descending)
