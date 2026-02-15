import math


def area_circle(radius: float) -> float:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    return round(math.pi * radius ** 2, 4)
