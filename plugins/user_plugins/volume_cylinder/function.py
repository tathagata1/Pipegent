import math


def volume_cylinder(radius: float, height: float) -> float:
    if radius < 0 or height < 0:
        raise ValueError("radius and height must be non-negative")
    return round(math.pi * radius ** 2 * height, 4)
