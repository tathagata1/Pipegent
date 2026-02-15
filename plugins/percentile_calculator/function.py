from typing import List


def percentile_calculator(numbers: List[float], percentile: float) -> float:
    if not numbers:
        raise ValueError('numbers cannot be empty')
    if percentile < 0 or percentile > 100:
        raise ValueError('percentile must be between 0 and 100')
    sorted_nums = sorted(numbers)
    if len(sorted_nums) == 1:
        return sorted_nums[0]
    rank = (percentile / 100) * (len(sorted_nums) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_nums) - 1)
    weight = rank - lower
    return sorted_nums[lower] * (1 - weight) + sorted_nums[upper] * weight
