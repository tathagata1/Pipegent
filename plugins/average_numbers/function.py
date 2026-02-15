from statistics import mean
from typing import List

def average_numbers(numbers: List[float]) -> dict:
    if not numbers:
        raise ValueError("numbers list cannot be empty")
    avg = mean(numbers)
    return {
        "average": round(avg, 4),
        "minimum": min(numbers),
        "maximum": max(numbers),
        "count": len(numbers)
    }
