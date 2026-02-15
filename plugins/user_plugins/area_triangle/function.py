def area_triangle(base: float, height: float) -> float:
    if base < 0 or height < 0:
        raise ValueError("base and height must be non-negative")
    return round(0.5 * base * height, 4)
