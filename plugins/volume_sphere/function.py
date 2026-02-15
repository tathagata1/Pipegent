import math


def volume_sphere(radius: float) -> float:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    return round((4 / 3) * math.pi * radius ** 3, 4)
